from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.i18n import t
from app.keyboards.barber import get_barber_main_menu, get_barber_order_actions
from app.keyboards.client import get_payment_methods_keyboard
from app.keyboards.common import btn, get_back_to_main_keyboard, get_role_main_menu, menu_label
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus, UserRole
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.authorization import (
    AuthorizationError,
    assert_can_manage_order,
    assert_can_manage_service,
)
from app.services.manual_payment_service import REJECT_REASONS, ManualPaymentError, ManualPaymentService
from app.services.notification_service import NotificationService
from app.services.payment_service import PaymentException, PaymentService
from app.services.queue_service import QueueService
from app.utils.formatting import format_money
from app.utils.time_utils import format_datetime, format_time, now_utc

logger = logging.getLogger(__name__)
router = Router(name="barber_router")


class WalkinSG(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_service = State()


class AddServiceSG(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_duration = State()


def is_staff(user: User) -> bool:
    return user.role in [UserRole.BARBER.value, UserRole.OWNER.value]


# -------------------------------------------------------------
# Barber Live Queue View
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("barber.menu_queue", "uz"),
    menu_label("barber.menu_queue", "uz_cyrl"),
    menu_label("barber.menu_queue", "ru"),
]))
@router.callback_query(F.data == "b_menu:queue")
async def handle_barber_queue(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_staff(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if not barber:
        await target_msg.answer(t("barber.profile_not_found", lang=lang))
        return

    order_repo = OrderRepository(session)
    active_orders = await order_repo.get_active_orders_for_barber(barber.id)

    status_str = t("barber.status_paused", lang=lang) if barber.is_paused else t("barber.status_active", lang=lang)
    header = t("barber.queue_header", lang=lang, status=status_str)

    if not active_orders:
        await target_msg.answer(f"{header}{t('barber.queue_empty', lang=lang)}", reply_markup=get_back_to_main_keyboard(lang))
        return

    await target_msg.answer(header)

    # Display each active order with contextual action buttons
    for idx, o in enumerate(active_orders, 1):
        nick = o.display_name_for(user)
        time_str = format_time(o.started_at or o.called_at or o.created_at)

        if o.status == OrderStatus.IN_SERVICE.value:
            text = t(
                "barber.current_client",
                lang=lang,
                ticket_no=o.ticket_no,
                nick=nick,
                service=o.service_name,
                time=time_str,
            )
        elif o.status == OrderStatus.CALLED.value:
            remaining = 0
            if o.deadline_at:
                remaining = max(0, int((o.deadline_at - now_utc()).total_seconds() / 60))
            text = t(
                "barber.called_client",
                lang=lang,
                ticket_no=o.ticket_no,
                nick=nick,
                remaining=remaining,
            )
        else:
            text = t(
                "barber.waiting_item",
                lang=lang,
                pos=idx,
                ticket_no=o.ticket_no,
                nick=nick,
                service=o.service_name,
            )

        markup = get_barber_order_actions(o, lang=lang)
        await target_msg.answer(text, reply_markup=markup)

    await target_msg.answer(t("common.back_to_main_menu", lang=lang), reply_markup=get_back_to_main_keyboard(lang))


# -------------------------------------------------------------
# Queue Actions: Keldi, Kelmadi, Done, Cash, Cancel
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("b_arrived:"))
async def handle_b_arrived(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        logger.warning("Non-staff user %s attempted b_arrived callback", getattr(user, "id", None))
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order:
        await call.answer(t("common.order_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_order(user, order, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_order", lang=lang), show_alert=True)
        return

    if order.status == OrderStatus.WAITING.value:
        await call.answer(t("barber.client_not_called_yet", lang=lang), show_alert=True)
        return

    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.client_arrived(order_id)
    await session.commit()

    if order:
        await call.answer(t("barber.arrived_success", lang=lang, ticket_no=order.ticket_no))
        if call.message and hasattr(call.message, "edit_reply_markup"):
            try:
                await call.message.edit_reply_markup(reply_markup=get_barber_order_actions(order, lang=lang))
            except Exception:
                pass


@router.callback_query(F.data.startswith("b_no_show:"))
async def handle_b_no_show(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        logger.warning("Non-staff user %s attempted b_no_show callback", getattr(user, "id", None))
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order:
        await call.answer(t("common.order_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_order(user, order, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_order", lang=lang), show_alert=True)
        return

    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.handle_lateness(order_id)
    await session.commit()

    if order:
        await call.answer(t("barber.no_show_success", lang=lang, ticket_no=order.ticket_no))
        if call.message and hasattr(call.message, "delete"):
            try:
                await call.message.delete()
            except Exception:
                pass


@router.callback_query(F.data.startswith("b_done:"))
async def handle_b_done(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        logger.warning("Non-staff user %s attempted b_done callback", getattr(user, "id", None))
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order:
        await call.answer(t("common.order_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_order(user, order, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_order", lang=lang), show_alert=True)
        return

    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order, changed = await qs.complete_service(order_id)
    await session.commit()

    if not order:
        await call.answer(t("common.order_not_found", lang=lang), show_alert=True)
        return

    # N2: only send pay prompt/receipt if changed is True and status == COMPLETED
    if not changed or order.status != OrderStatus.COMPLETED.value:
        await call.answer(t("barber.order_already_processed", lang=lang), show_alert=True)
        if call.message and hasattr(call.message, "delete"):
            try:
                await call.message.delete()
            except Exception:
                pass
        return

    await call.answer(t("barber.done_success", lang=lang, ticket_no=order.ticket_no))
    if call.message and hasattr(call.message, "delete"):
        try:
            await call.message.delete()
        except Exception:
            pass

    # If order is completed and unpaid, prompt client with payment options;
    # if already paid, send thank-you/receipt only without payment keyboard
    payment_repo = PaymentRepository(session)
    payment = await payment_repo.get_paid_by_order_id(order.id)
    if not payment:
        if order.client:
            pay_prompt = t(
                "client.service_completed_pay_prompt",
                lang=order.client.language,
                amount=order.price,
            )
            markup = get_payment_methods_keyboard(order.id, lang=order.client.language)
            await bot.send_message(
                chat_id=order.client.telegram_id,
                text=pay_prompt,
                reply_markup=markup,
            )
    else:
        if order.client:
            receipt_text = t(
                "client.service_completed_receipt",
                lang=order.client.language,
                amount=order.price,
            )
            await bot.send_message(
                chat_id=order.client.telegram_id,
                text=receipt_text,
            )


@router.callback_query(F.data.startswith("b_cash:"))
async def handle_b_cash(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        logger.warning("Non-staff user %s attempted b_cash callback", getattr(user, "id", None))
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order:
        await call.answer(t("common.order_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_order(user, order, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_order", lang=lang), show_alert=True)
        return

    # N2: only allow cash confirmation when order is COMPLETED
    if order.status != OrderStatus.COMPLETED.value:
        logger.warning("Attempted cash confirmation on order #%d in status %s", order.id, order.status)
        await call.answer(t("payments.err_order_not_completed", lang=lang), show_alert=True)
        return

    payment_service = PaymentService(session, notifier=NotificationService(bot=bot))
    try:
        payment = await payment_service.confirm_cash_payment(order_id, user.id)
        await session.commit()
    except PaymentException as exc:
        logger.warning("Cash confirmation failed for order #%d: %s", order_id, exc)
        await call.answer(t("payments.err_already_paid", lang=lang), show_alert=True)
        return

    ticket_no = order.ticket_no if order else order_id
    amount_str = format_money(payment.amount)

    await call.answer(t("barber.cash_success", lang=lang, ticket_no=ticket_no, amount=amount_str), show_alert=True)
    if call.message and hasattr(call.message, "delete"):
        try:
            await call.message.delete()
        except Exception:
            pass


async def _transfer_staff_context(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    """Returns (ok, barber). Answers the callback itself when the user may not review receipts."""
    if not is_staff(user):
        logger.warning("Non-staff user %s attempted a receipt review callback", getattr(user, "id", None))
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return False, None
    barber = await BarberRepository(session).get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return False, None
    return True, barber


async def _clear_buttons(call: CallbackQuery) -> None:
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("tr_ok:"))
async def handle_transfer_confirm(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    ok, barber = await _transfer_staff_context(call, session, user, lang)
    if not ok:
        return
    payment_id = int(call.data.split(":")[1])
    service = ManualPaymentService(session, notifier=NotificationService(bot=bot))
    try:
        result = await service.confirm_transfer(payment_id, user, barber=barber)
        await session.commit()
    except AuthorizationError:
        await session.rollback()
        await call.answer(t("barber.unauthorized_order", lang=lang), show_alert=True)
        return
    except ManualPaymentError:
        await session.rollback()
        await call.answer(t("payments.tr_already_handled", lang=lang), show_alert=True)
        await _clear_buttons(call)
        return

    await _clear_buttons(call)
    if result.refund_flagged:
        await call.answer(t("payments.tr_refund_flagged", lang=lang), show_alert=True)
    elif not result.changed:
        await call.answer(t("payments.tr_already_handled", lang=lang), show_alert=True)
    else:
        await call.answer(t("payments.tr_confirmed_ok", lang=lang, amount=format_money(result.payment.amount)), show_alert=True)
        await service.notify_client_confirmed(result.payment)


@router.callback_query(F.data.startswith("tr_no:"))
async def handle_transfer_reject_prompt(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    ok, _ = await _transfer_staff_context(call, session, user, lang)
    if not ok:
        return
    payment_id = int(call.data.split(":")[1])
    rows = [
        [btn(text=t(f"payments.btn_reason_{code.lower()}", lang=lang), callback_data=f"tr_why:{payment_id}:{code}", style="danger")]
        for code in REJECT_REASONS
    ]
    try:
        await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:
        pass
    await call.answer(t("payments.tr_pick_reason", lang=lang))


@router.callback_query(F.data.startswith("tr_why:"))
async def handle_transfer_reject(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    ok, barber = await _transfer_staff_context(call, session, user, lang)
    if not ok:
        return
    _, payment_id_str, reason = call.data.split(":")
    service = ManualPaymentService(session, notifier=NotificationService(bot=bot))
    try:
        result = await service.reject_transfer(int(payment_id_str), user, reason, barber=barber)
        await session.commit()
    except AuthorizationError:
        await session.rollback()
        await call.answer(t("barber.unauthorized_order", lang=lang), show_alert=True)
        return
    except ManualPaymentError:
        await session.rollback()
        await call.answer(t("payments.tr_already_handled", lang=lang), show_alert=True)
        await _clear_buttons(call)
        return

    await _clear_buttons(call)
    if not result.changed:
        await call.answer(t("payments.tr_already_handled", lang=lang), show_alert=True)
        return
    await call.answer(t("payments.tr_rejected_ok", lang=lang), show_alert=True)
    await service.notify_client_rejected(result.payment, reason)


@router.callback_query(F.data.startswith("b_cancel:"))
async def handle_b_cancel(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        logger.warning("Non-staff user %s attempted b_cancel callback", getattr(user, "id", None))
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order:
        await call.answer(t("common.order_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_order(user, order, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_order", lang=lang), show_alert=True)
        return

    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.cancel_by_staff(order_id, user.id)
    await session.commit()

    ticket_no = order.ticket_no if order else order_id
    await call.answer(t("barber.cancel_success", lang=lang, ticket_no=ticket_no))
    if call.message and hasattr(call.message, "delete"):
        try:
            await call.message.delete()
        except Exception:
            pass


# -------------------------------------------------------------
# Toggle Status (Ishda / Dam olish)
# -------------------------------------------------------------
@router.callback_query(F.data == "b_menu:toggle_status")
async def handle_toggle_status_callback(
    call: CallbackQuery, session: AsyncSession, user: User, lang: str
):
    if not is_staff(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if not barber:
        return

    new_status = not barber.is_paused
    await barber_repo.set_paused(barber.id, new_status)
    await session.commit()
    barber.is_paused = new_status

    alert_msg = t("barber.toggled_paused", lang=lang) if new_status else t("barber.toggled_active", lang=lang)
    await call.answer(alert_msg, show_alert=True)

    from app.handlers.common import render_role_main_dashboard
    text, markup = await render_role_main_dashboard(session, user)
    try:
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(F.text.in_([
    menu_label("barber.menu_toggle_status", "uz"),
    menu_label("barber.menu_toggle_status", "uz_cyrl"),
    menu_label("barber.menu_toggle_status", "ru"),
]))
async def handle_toggle_status(message: Message, session: AsyncSession, user: User, lang: str):
    if not is_staff(user):
        return

    from app.handlers.common import remove_reply_markup
    await remove_reply_markup(message)

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if not barber:
        return

    new_status = not barber.is_paused
    await barber_repo.set_paused(barber.id, new_status)
    await session.commit()
    barber.is_paused = new_status

    alert_text = t("barber.toggled_paused", lang=lang) if new_status else t("barber.toggled_active", lang=lang)
    from app.handlers.common import render_role_main_dashboard
    text, markup = await render_role_main_dashboard(session, user)
    await message.answer(f"{alert_text}\n\n{text}", reply_markup=markup, parse_mode="HTML")


# -------------------------------------------------------------
# Barber Payments (Own payments only, NO totals, NO reports)
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("barber.menu_payments", "uz"),
    menu_label("barber.menu_payments", "uz_cyrl"),
    menu_label("barber.menu_payments", "ru"),
]))
@router.callback_query(F.data == "b_menu:payments")
async def handle_barber_payments(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_staff(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if not barber:
        return

    payment_repo = PaymentRepository(session)
    payments = await payment_repo.get_barber_payments(barber.id, limit=20)
    if not payments:
        await target_msg.answer(t("barber.my_payments_empty", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return

    lines = [t("barber.my_payments_title", lang=lang)]
    for p in payments:
        time_str = format_datetime(p.paid_at)
        nick = p.order.client_display_name if p.order else (p.client.display_nick if p.client else "Mijoz")
        amount_str = format_money(p.amount)
        service_name = p.order.service_name if p.order else ""
        lines.append(
            t(
                "barber.my_payments_item",
                lang=lang,
                time=time_str,
                nick=nick,
                amount=amount_str,
                method=p.method,
                service=service_name,
            )
        )
    await target_msg.answer("".join(lines), reply_markup=get_back_to_main_keyboard(lang))


@router.message(F.text.in_([
    menu_label("barber.menu_pending_receipts", "uz"),
    menu_label("barber.menu_pending_receipts", "uz_cyrl"),
    menu_label("barber.menu_pending_receipts", "ru"),
]))
@router.callback_query(F.data == "b_menu:pending_receipts")
async def handle_barber_pending_receipts(
    event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str
):
    if not is_staff(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    barber_id = barber.id if barber else None

    payment_repo = PaymentRepository(session)
    pending_payments = await payment_repo.get_pending_receipts(
        barber_id=barber_id if user.role != UserRole.OWNER.value else None
    )

    if not pending_payments:
        await target_msg.answer(
            t("barber.no_pending_receipts", lang=lang),
            reply_markup=get_back_to_main_keyboard(lang),
        )
        return

    title_text = t("barber.pending_receipts_title", lang=lang)
    await target_msg.answer(title_text)

    for p in pending_payments:
        order = p.order
        nick = order.display_name_for(user) if order else "Mijoz"
        ticket_no = order.ticket_no if order else "?"
        service_name = order.service_name if order else "?"
        caption = t(
            "payments.transfer_review_caption",
            lang=lang,
            nick=nick,
            ticket_no=ticket_no,
            service=service_name,
            amount=format_money(p.amount),
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            btn(text=t("payments.btn_transfer_ok", lang=lang), callback_data=f"tr_ok:{p.id}", style="success", icon="check"),
            btn(text=t("payments.btn_transfer_no", lang=lang), callback_data=f"tr_no:{p.id}", style="danger", icon="cross"),
        ]])
        if p.receipt_file_id:
            await target_msg.answer_photo(p.receipt_file_id, caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await target_msg.answer(caption, reply_markup=kb, parse_mode="HTML")


# -------------------------------------------------------------
# Walk-in Client (Manual client addition without Telegram)
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("barber.menu_walkin", "uz"),
    menu_label("barber.menu_walkin", "uz_cyrl"),
    menu_label("barber.menu_walkin", "ru"),
]))
@router.callback_query(F.data == "b_menu:walkin")
async def handle_add_walkin(event: Message | CallbackQuery, session: AsyncSession, user: User, state: FSMContext, lang: str):
    if not is_staff(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    await state.set_state(WalkinSG.waiting_for_name)
    await target_msg.answer(t("barber.walkin_name_prompt", lang=lang), reply_markup=get_back_to_main_keyboard(lang))


@router.message(WalkinSG.waiting_for_name)
async def handle_walkin_name(message: Message, state: FSMContext, lang: str):
    name = (message.text or "").strip()
    if not name:
        return
    await state.update_data(walkin_name=name)
    await state.set_state(WalkinSG.waiting_for_phone)
    await message.answer(t("barber.walkin_phone_prompt", lang=lang))


@router.message(WalkinSG.waiting_for_phone)
async def handle_walkin_phone(
    message: Message,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    lang: str,
):
    phone = (message.text or "").strip()
    if phone == t("common.skip", lang=lang):
        phone = ""
    await state.update_data(walkin_phone=phone)

    # Show services
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    services = await barber_repo.get_services(barber.id, active_only=True)

    rows = []
    for s in services:
        rows.append([
            btn(
                text=f"{s.name} — {format_money(s.price)}",
                callback_data=f"walkin_svc:{s.id}",
            )
        ])
    await state.set_state(WalkinSG.waiting_for_service)
    await message.answer(t("client.choose_service", lang=lang), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(WalkinSG.waiting_for_service, F.data.startswith("walkin_svc:"))
async def handle_walkin_service(
    call: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
    lang: str,
):
    if not is_staff(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    svc_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    service = await barber_repo.get_service_by_id(svc_id)
    if not service:
        await call.answer(t("common.service_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_service(user, service, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_service", lang=lang), show_alert=True)
        return

    data = await state.get_data()
    walkin_name = data.get("walkin_name", "Mijoz")
    walkin_phone = data.get("walkin_phone", "")

    acting_barber_id = service.barber_id if user.role == UserRole.OWNER.value else barber.id

    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.join_queue(
        barber_id=acting_barber_id,
        service_id=svc_id,
        client=None,
        walkin_name=walkin_name,
        walkin_phone=walkin_phone,
        pay_now=False,
        enforce_capacity=False,  # the barber is physically present and decides who he takes
    )
    await session.commit()
    await state.clear()

    await call.message.delete()
    success_text = t(
        "barber.walkin_success",
        lang=lang,
        ticket_no=order.ticket_no,
        name=walkin_name,
        service=order.service_name,
    )
    from app.handlers.common import render_role_main_dashboard
    dash_text, dash_markup = await render_role_main_dashboard(session, user)
    await call.message.answer(f"{success_text}\n\n{dash_text}", reply_markup=dash_markup, parse_mode="HTML")


# -------------------------------------------------------------
# Barber Services Management
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("barber.menu_services", "uz"),
    menu_label("barber.menu_services", "uz_cyrl"),
    menu_label("barber.menu_services", "ru"),
]))
@router.callback_query(F.data == "b_menu:services")
async def handle_barber_services(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_staff(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
        is_cb = True
    else:
        target_msg = event
        is_cb = False
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if not barber:
        return

    services = await barber_repo.get_services(barber.id, active_only=False)

    rows = []
    for s in services:
        status_icon = "🟢" if s.is_active else "🔴"
        icon_name = "green" if s.is_active else "red"
        rows.append([
            btn(
                text=f"{status_icon} {s.name} ({format_money(s.price)}, {s.duration_minutes}m)",
                callback_data=f"toggle_svc:{s.id}",
                icon=icon_name,
            )
        ])

    if settings.ALLOW_BARBER_EDIT_OWN_SERVICES or user.role == UserRole.OWNER.value:
        rows.append([
            btn(text=t("barber.service_add_btn", lang=lang), callback_data="add_svc_prompt", style="success", icon="plus")
        ])

    rows.append([
        btn(text=t("common.btn_back_main", lang=lang), callback_data="back_to_main_menu", icon="home")
    ])

    title = t("barber.services_title", lang=lang)
    if is_cb:
        await target_msg.edit_text(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    else:
        await target_msg.answer(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("toggle_svc:") | F.data.startswith("b_svc_toggle:"))
async def handle_toggle_service(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_staff(user):
        logger.warning("Non-staff user %s attempted service toggle", getattr(user, "id", None))
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    if user.role != UserRole.OWNER.value and not settings.ALLOW_BARBER_EDIT_OWN_SERVICES:
        await call.answer(t("barber.edit_services_forbidden", lang=lang), show_alert=True)
        return

    svc_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    service = await barber_repo.get_service_by_id(svc_id)
    if not service:
        await call.answer(t("common.service_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_service(user, service, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_service", lang=lang), show_alert=True)
        return

    await barber_repo.toggle_service(svc_id)
    await session.commit()

    await call.answer(t("common.status_updated", lang=lang))
    # Refresh list
    target_barber_id = service.barber_id if user.role == UserRole.OWNER.value else (barber.id if barber else service.barber_id)
    services = await barber_repo.get_services(target_barber_id, active_only=False)
    rows = []
    for s in services:
        status_icon = "🟢" if s.is_active else "🔴"
        icon_name = "green" if s.is_active else "red"
        rows.append([
            btn(
                text=f"{status_icon} {s.name} ({format_money(s.price)}, {s.duration_minutes}m)",
                callback_data=f"toggle_svc:{s.id}",
                icon=icon_name,
            )
        ])
    if settings.ALLOW_BARBER_EDIT_OWN_SERVICES or user.role == UserRole.OWNER.value:
        rows.append([
            btn(text=t("barber.service_add_btn", lang=lang), callback_data="add_svc_prompt", style="success", icon="plus")
        ])
    rows.append([
        btn(text=t("common.btn_back_main", lang=lang), callback_data="back_to_main_menu", icon="home")
    ])
    if call.message and hasattr(call.message, "edit_reply_markup"):
        try:
            await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except Exception:
            pass


@router.callback_query(F.data.startswith("b_svc_edit_price:"))
async def handle_edit_service_price(call: CallbackQuery, session: AsyncSession, user: User, state: FSMContext, lang: str):
    if not is_staff(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    if user.role != UserRole.OWNER.value and not settings.ALLOW_BARBER_EDIT_OWN_SERVICES:
        await call.answer(t("barber.edit_services_forbidden", lang=lang), show_alert=True)
        return

    svc_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    service = await barber_repo.get_service_by_id(svc_id)
    if not service:
        await call.answer(t("common.service_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_service(user, service, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_service", lang=lang), show_alert=True)
        return

    await state.update_data(edit_svc_id=svc_id)
    await state.set_state(AddServiceSG.waiting_for_price)
    await call.message.answer(t("barber.enter_service_price", lang=lang))
    await call.answer()


@router.callback_query(F.data.startswith("b_svc_edit_name:"))
async def handle_edit_service_name(call: CallbackQuery, session: AsyncSession, user: User, state: FSMContext, lang: str):
    if not is_staff(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    if user.role != UserRole.OWNER.value and not settings.ALLOW_BARBER_EDIT_OWN_SERVICES:
        await call.answer(t("barber.edit_services_forbidden", lang=lang), show_alert=True)
        return

    svc_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    service = await barber_repo.get_service_by_id(svc_id)
    if not service:
        await call.answer(t("common.service_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_service(user, service, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_service", lang=lang), show_alert=True)
        return

    await state.update_data(edit_svc_id=svc_id)
    await state.set_state(AddServiceSG.waiting_for_name)
    await call.message.answer(t("barber.enter_service_name", lang=lang))
    await call.answer()


@router.callback_query(F.data.startswith("b_svc_edit_duration:"))
async def handle_edit_service_duration(call: CallbackQuery, session: AsyncSession, user: User, state: FSMContext, lang: str):
    if not is_staff(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    if user.role != UserRole.OWNER.value and not settings.ALLOW_BARBER_EDIT_OWN_SERVICES:
        await call.answer(t("barber.edit_services_forbidden", lang=lang), show_alert=True)
        return

    svc_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if user.role != UserRole.OWNER.value and not barber:
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    service = await barber_repo.get_service_by_id(svc_id)
    if not service:
        await call.answer(t("common.service_not_found", lang=lang), show_alert=True)
        return

    try:
        assert_can_manage_service(user, service, barber=barber)
    except AuthorizationError:
        await call.answer(t("barber.unauthorized_service", lang=lang), show_alert=True)
        return

    await state.update_data(edit_svc_id=svc_id)
    await state.set_state(AddServiceSG.waiting_for_duration)
    await call.message.answer(t("barber.enter_service_duration", lang=lang))
    await call.answer()


@router.callback_query(F.data == "add_svc_prompt")
async def handle_add_service_prompt(call: CallbackQuery, state: FSMContext, user: User, lang: str):
    if not is_staff(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    if user.role != UserRole.OWNER.value and not settings.ALLOW_BARBER_EDIT_OWN_SERVICES:
        await call.answer(t("barber.edit_services_forbidden", lang=lang), show_alert=True)
        return

    await state.set_state(AddServiceSG.waiting_for_name)
    await call.message.answer(t("barber.enter_service_name", lang=lang))
    await call.answer()


@router.message(AddServiceSG.waiting_for_name)
async def handle_add_svc_name(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str
):
    if not is_staff(user):
        await state.clear()
        return
    if user.role != UserRole.OWNER.value and not settings.ALLOW_BARBER_EDIT_OWN_SERVICES:
        await state.clear()
        await message.answer(t("barber.edit_services_forbidden", lang=lang))
        return

    name = (message.text or "").strip()
    if not name:
        return

    data = await state.get_data()
    edit_svc_id = data.get("edit_svc_id")
    if edit_svc_id:
        barber_repo = BarberRepository(session)
        await barber_repo.update_service(edit_svc_id, name=name)
        await session.commit()
        await state.clear()
        await message.answer(t("barber.service_name_updated", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return

    await state.update_data(svc_name=name)
    await state.set_state(AddServiceSG.waiting_for_price)
    await message.answer(t("barber.enter_service_price", lang=lang))


@router.message(AddServiceSG.waiting_for_price)
async def handle_add_svc_price(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str
):
    if not is_staff(user):
        await state.clear()
        return
    if user.role != UserRole.OWNER.value and not settings.ALLOW_BARBER_EDIT_OWN_SERVICES:
        await state.clear()
        await message.answer(t("barber.edit_services_forbidden", lang=lang))
        return

    text = (message.text or "").strip().replace(" ", "")
    if not text.isdigit():
        await message.answer(t("barber.enter_service_price", lang=lang))
        return
    price = int(text)
    if price <= 0:
        await message.answer(t("barber.err_invalid_price", lang=lang))
        return

    data = await state.get_data()
    edit_svc_id = data.get("edit_svc_id")
    if edit_svc_id:
        barber_repo = BarberRepository(session)
        await barber_repo.update_service(edit_svc_id, price=price)
        await session.commit()
        await state.clear()
        await message.answer(t("barber.service_price_updated", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return

    await state.update_data(svc_price=price)
    await state.set_state(AddServiceSG.waiting_for_duration)
    await message.answer(t("barber.enter_service_duration", lang=lang))


@router.message(AddServiceSG.waiting_for_duration)
async def handle_add_svc_duration(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str
):
    if not is_staff(user):
        await state.clear()
        return
    if user.role != UserRole.OWNER.value and not settings.ALLOW_BARBER_EDIT_OWN_SERVICES:
        await state.clear()
        await message.answer(t("barber.edit_services_forbidden", lang=lang))
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(t("barber.enter_service_duration", lang=lang))
        return
    duration = int(text)
    if duration < 5 or duration > 480:
        await message.answer(t("barber.err_invalid_duration", lang=lang))
        return

    data = await state.get_data()
    edit_svc_id = data.get("edit_svc_id")
    if edit_svc_id:
        barber_repo = BarberRepository(session)
        await barber_repo.update_service(edit_svc_id, duration_minutes=duration)
        await session.commit()
        await state.clear()
        await message.answer(t("barber.service_duration_updated", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return

    svc_name = data.get("svc_name", "Xizmat")
    svc_price = data.get("svc_price", 50000)
    target_barber_id = data.get("target_barber_id")

    barber_repo = BarberRepository(session)
    if not target_barber_id:
        barber = await barber_repo.get_by_user_id(user.id)
        target_barber_id = barber.id if barber else None

    if target_barber_id:
        await barber_repo.create_service(target_barber_id, svc_name, svc_price, duration)
        await session.commit()
    await state.clear()

    await message.answer(t("barber.service_added", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
