from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.i18n import t
from app.keyboards.client import (
    get_barbers_keyboard,
    get_cancel_confirm_keyboard,
    get_my_queue_keyboard,
    get_payment_methods_keyboard,
    get_payment_timing_keyboard,
    get_receipt_cancel_keyboard,
    get_receipt_prompt_keyboard,
    get_services_keyboard,
)
from app.keyboards.common import menu_label
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.manual_payment_service import (
    AlreadyPaidError,
    DuplicateReceiptError,
    ManualPaymentService,
    OrderNotPayableError,
)
from app.services.notification_service import NotificationService
from app.services.payment_service import PaymentService
from app.services.queue_service import (
    AlreadyInQueueError,
    BarberClosedError,
    CannotCancelInServiceError,
    QueueFullError,
    QueueService,
)
from app.utils.formatting import format_money
from app.utils.time_utils import format_datetime

logger = logging.getLogger(__name__)
router = Router(name="client_router")


class ReceiptSG(StatesGroup):
    waiting_photo = State()


def _queue_full_text(reason: str, lang: str) -> str:
    key = "client.queue_full_max" if reason == "MAX_QUEUE" else "client.queue_full_closing"
    return t(key, lang=lang, max=settings.MAX_QUEUE_PER_BARBER)


@router.message(F.text.in_([
    menu_label("client.menu_join", "uz"),
    menu_label("client.menu_join", "uz_cyrl"),
    menu_label("client.menu_join", "ru"),
]))
@router.callback_query(F.data == "c_menu:join")
async def handle_join_queue_menu(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    if not user.phone:
        from app.keyboards.common import get_client_phone_registration_keyboard
        prompt_reg = t("client.phone_required_to_join", lang=lang)
        await target_msg.answer(prompt_reg, reply_markup=get_client_phone_registration_keyboard(lang), parse_mode="HTML")
        return

    order_repo = OrderRepository(session)
    active_order = await order_repo.get_active_order_for_client(user.id)
    if active_order:
        await target_msg.answer(t("client.already_in_queue", lang=lang))
        await show_active_queue(target_msg, session, active_order, lang)
        return

    barber_repo = BarberRepository(session)
    qs = QueueService(session)
    active_barbers = await barber_repo.get_all_active()

    barbers_with_metrics = []
    for barber in active_barbers:
        q_len, wait_min = await qs.get_barber_queue_metrics(barber.id)
        is_open = qs.is_barber_open(barber, wait_min)
        barbers_with_metrics.append((barber, q_len, wait_min, is_open))

    prompt = t("client.choose_barber", lang=lang)
    markup = get_barbers_keyboard(barbers_with_metrics, lang=lang)
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(prompt, reply_markup=markup)
            return
        except Exception:
            pass
    await target_msg.answer(prompt, reply_markup=markup)


@router.callback_query(F.data == "noop:closed")
async def handle_noop_closed(call: CallbackQuery, lang: str):
    await call.answer(t("client.barber_closed", lang=lang), show_alert=True)


@router.callback_query(F.data.startswith("choose_barber:"))
async def handle_choose_barber(call: CallbackQuery, session: AsyncSession, lang: str):
    target = call.data.split(":")[1]
    barber_repo = BarberRepository(session)
    qs = QueueService(session)

    if target == "any":
        # Select barber with shortest estimated wait time
        active_barbers = await barber_repo.get_all_active()
        candidates = []
        for b in active_barbers:
            q_len, wait_min = await qs.get_barber_queue_metrics(b.id)
            if qs.is_barber_open(b, wait_min) and q_len < settings.MAX_QUEUE_PER_BARBER:
                candidates.append((b, wait_min))

        if not candidates:
            await call.answer(t("client.barber_closed", lang=lang), show_alert=True)
            return
        candidates.sort(key=lambda c: c[1])
        selected_barber = candidates[0][0]
    else:
        barber_id = int(target)
        selected_barber = await barber_repo.get_by_id(barber_id)
        if not selected_barber:
            await call.answer(t("common.barber_not_found", lang=lang), show_alert=True)
            return

        q_len, wait_min = await qs.get_barber_queue_metrics(selected_barber.id)
        if not qs.is_barber_open(selected_barber, wait_min):
            await call.answer(t("client.barber_closed", lang=lang), show_alert=True)
            return

    services = await barber_repo.get_services(selected_barber.id, active_only=True)
    if not services:
        await call.answer(t("client.no_active_services", lang=lang), show_alert=True)
        return

    prompt = f"💈 {selected_barber.display_name}\n\n{t('client.choose_service', lang=lang)}"
    markup = get_services_keyboard(services, selected_barber.id, lang=lang)
    await call.message.edit_text(prompt, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "back_to_barbers")
async def handle_back_to_barbers(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    barber_repo = BarberRepository(session)
    qs = QueueService(session)
    active_barbers = await barber_repo.get_all_active()

    barbers_with_metrics = []
    for barber in active_barbers:
        q_len, wait_min = await qs.get_barber_queue_metrics(barber.id)
        is_open = qs.is_barber_open(barber, wait_min)
        barbers_with_metrics.append((barber, q_len, wait_min, is_open))

    prompt = t("client.choose_barber", lang=lang)
    markup = get_barbers_keyboard(barbers_with_metrics, lang=lang)
    await call.message.edit_text(prompt, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("choose_service:"))
async def handle_choose_service(call: CallbackQuery, session: AsyncSession, lang: str):
    _, barber_id_str, service_id_str = call.data.split(":")
    barber_id = int(barber_id_str)
    service_id = int(service_id_str)

    barber_repo = BarberRepository(session)
    qs = QueueService(session)

    barber = await barber_repo.get_by_id(barber_id)
    service = await barber_repo.get_service_by_id(service_id)
    if not barber or not service:
        await call.answer(t("common.service_not_found", lang=lang), show_alert=True)
        return

    q_len, wait_min = await qs.get_barber_queue_metrics(barber.id)
    if not qs.is_barber_open(barber, wait_min):
        await call.answer(t("client.barber_closed", lang=lang), show_alert=True)
        return

    active_orders = await qs.order_repo.get_active_orders_for_barber(barber.id)
    block = qs.capacity_block_reason(barber, active_orders, service.duration_minutes)
    if block:
        await call.answer(_queue_full_text(block, lang), show_alert=True)
        return

    pos = q_len + 1
    ahead = q_len

    confirm_text = t(
        "client.confirm_order",
        lang=lang,
        barber=barber.display_name,
        service=service.name,
        price=format_money(service.price),
        pos=pos,
        ahead=ahead,
        wait_min=wait_min,
    ) + "\n" + t("client.eta_line", lang=lang, eta=QueueService.estimated_start_text(wait_min))
    markup = get_payment_timing_keyboard(barber_id, service_id, lang=lang)
    await call.message.edit_text(confirm_text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("pay_timing:"))
async def handle_pay_timing(
    call: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    lang: str,
):
    _, timing, barber_id_str, service_id_str = call.data.split(":")
    barber_id = int(barber_id_str)
    service_id = int(service_id_str)

    notifier = NotificationService(bot=bot)
    qs = QueueService(session, notifier=notifier)

    pay_now = (timing == "now")
    try:
        order = await qs.join_queue(
            barber_id=barber_id,
            service_id=service_id,
            client=user,
            pay_now=pay_now,
        )
        await session.commit()
    except AlreadyInQueueError:
        await call.answer(t("client.already_in_queue", lang=lang), show_alert=True)
        return
    except BarberClosedError:
        await call.answer(t("client.barber_closed", lang=lang), show_alert=True)
        return
    except QueueFullError as exc:
        await call.answer(_queue_full_text(exc.reason, lang), show_alert=True)
        return

    if pay_now:
        # Prompt payment methods
        msg = t("client.pending_payment_created", lang=lang)
        markup = get_payment_methods_keyboard(order.id, lang=lang)
        await call.message.edit_text(msg, reply_markup=markup)
    else:
        # Show queue ticket confirmation
        active_orders = await qs.order_repo.get_active_orders_for_barber(barber_id)
        pos, _, wait_min = qs.calculate_order_position_and_wait(order, active_orders)
        success_msg = t(
            "client.order_joined",
            lang=lang,
            ticket_no=order.ticket_no,
            barber=order.barber.display_name,
            pos=pos,
            wait_min=wait_min,
        ) + "\n" + t("client.eta_line", lang=lang, eta=QueueService.estimated_start_text(wait_min))
        markup = get_my_queue_keyboard(order.id, lang=lang)
        await call.message.edit_text(success_msg, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("pay_method:"))
async def handle_pay_method_selected(
    call: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    user: User,
    lang: str,
):
    _, order_id_str, method = call.data.split(":")
    order_id = int(order_id_str)

    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order or order.client_id != user.id:
        await call.answer(t("payments.err_foreign_payer", lang=lang), show_alert=True)
        return

    payment_service = PaymentService(session, notifier=NotificationService(bot=bot))

    if method in [PaymentMethod.CLICK.value, PaymentMethod.PAYME.value]:
        _, payload = await payment_service.get_or_create_pending_payment(order.id, method)
        await session.commit()

        provider_token = payload.get("provider_token", "")
        if not provider_token:
            if settings.PAYMENTS_MODE == "test" and settings.ENV != "production":
                # Fallback to test simulated payment in test mode only
                await payment_service.handle_successful_payment(
                    method=method,
                    provider_payment_id=f"test_{order.id}_{method}",
                    amount=order.price,
                    order_id=order.id,
                )
                await session.commit()
                await call.message.edit_text(
                    t("client.test_mode_success", lang=lang, method=method),
                    reply_markup=get_my_queue_keyboard(order.id, lang=lang),
                )
                return
            await call.answer(t("client.provider_token_not_configured", lang=lang, method=method), show_alert=True)
            return

        # Send Telegram invoice
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title=payload["title"],
            description=payload["description"],
            payload=payload["payload"],
            provider_token=provider_token,
            currency=payload["currency"],
            prices=[LabeledPrice(label=p["label"], amount=p["amount"]) for p in payload["prices"]],
        )
        await call.answer()

    elif method == PaymentMethod.PAYNET.value:
        if not settings.PAYNET_ENABLED or "PAYNET" not in settings.ENABLED_PAYMENT_METHODS:
            await call.answer(t("client.paynet_unavailable", lang=lang), show_alert=True)
            return

        _, payload = await payment_service.get_or_create_pending_payment(order.id, method)
        await session.commit()
        if not payload.get("available"):
            await call.answer(payload.get("error", t("client.paynet_unavailable", lang=lang)), show_alert=True)
            return
        checkout_url = payload.get("checkout_url", "")
        await call.message.edit_text(
            t("client.paynet_checkout_prompt", lang=lang, url=checkout_url),
            reply_markup=get_my_queue_keyboard(order.id, lang=lang),
        )

    elif method == PaymentMethod.CASH.value:
        if "CASH" not in settings.ENABLED_PAYMENT_METHODS:
            await call.answer(t("payments.transfer_err_not_payable", lang=lang), show_alert=True)
            return
        # Nothing is stored: the barber presses "Naqd to'landi" (b_cash) after the service
        await call.message.edit_text(
            t("payments.cash_instructions", lang=lang, amount=format_money(order.price)),
            reply_markup=get_my_queue_keyboard(order.id, lang=lang),
        )
        await call.answer()

    elif method == PaymentMethod.TRANSFER.value:
        card_digits = "".join(ch for ch in (settings.PAYMENT_CARD_NUMBER or "") if ch.isdigit())
        if "TRANSFER" not in settings.ENABLED_PAYMENT_METHODS or len(card_digits) != 16:
            await call.answer(t("payments.transfer_not_configured", lang=lang), show_alert=True)
            return
        if order.status not in (
            OrderStatus.WAITING.value, OrderStatus.CALLED.value, OrderStatus.IN_SERVICE.value, OrderStatus.COMPLETED.value
        ):
            await call.answer(t("payments.transfer_err_not_payable", lang=lang), show_alert=True)
            return
        if await PaymentRepository(session).get_paid_by_order_id(order.id):
            await call.answer(t("payments.err_already_paid", lang=lang), show_alert=True)
            return
        card_fmt = " ".join(card_digits[i:i + 4] for i in range(0, 16, 4))
        await call.message.edit_text(
            t(
                "payments.transfer_instructions",
                lang=lang,
                card=card_fmt,
                holder=settings.PAYMENT_CARD_HOLDER,
                amount=format_money(order.price),
            ),
            reply_markup=get_receipt_prompt_keyboard(order.id, lang=lang),
        )
        await call.answer()

    elif method == "FAKE":
        if settings.ENV == "production" or settings.PAYMENTS_MODE != "test":
            await call.answer(t("client.test_payments_disabled", lang=lang), show_alert=True)
            return

        # Instant test payment
        await payment_service.handle_successful_payment(
            method="FAKE",
            provider_payment_id=f"fake_{order.id}",
            amount=order.price,
            order_id=order.id,
        )
        await session.commit()
        await call.message.edit_text(
            t("client.test_payment_success", lang=lang),
            reply_markup=get_my_queue_keyboard(order.id, lang=lang),
        )


@router.callback_query(F.data.startswith("pay_open:"))
async def handle_pay_open(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    order_id = int(call.data.split(":")[1])
    order = await OrderRepository(session).get_by_id(order_id)
    if not order or order.client_id != user.id:
        await call.answer(t("payments.err_foreign_payer", lang=lang), show_alert=True)
        return
    if await PaymentRepository(session).get_paid_by_order_id(order.id):
        await call.answer(t("payments.err_already_paid", lang=lang), show_alert=True)
        return
    await call.message.edit_text(
        t("client.service_completed_pay_prompt", lang=lang, amount=order.price),
        reply_markup=get_payment_methods_keyboard(order.id, lang=lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("tr_send:"))
async def handle_receipt_send_prompt(call: CallbackQuery, session: AsyncSession, user: User, state: FSMContext, lang: str):
    order_id = int(call.data.split(":")[1])
    order = await OrderRepository(session).get_by_id(order_id)
    if not order or order.client_id != user.id:
        await call.answer(t("payments.err_foreign_payer", lang=lang), show_alert=True)
        return
    await state.set_state(ReceiptSG.waiting_photo)
    await state.update_data(receipt_order_id=order_id)
    await call.message.answer(
        t("payments.transfer_send_prompt", lang=lang),
        reply_markup=get_receipt_cancel_keyboard(lang=lang),
    )
    await call.answer()


@router.callback_query(F.data == "tr_cancel")
async def handle_receipt_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


@router.message(ReceiptSG.waiting_photo, F.photo)
async def handle_receipt_photo(
    message: Message, session: AsyncSession, user: User, bot: Bot, state: FSMContext, lang: str
):
    data = await state.get_data()
    order_id = data.get("receipt_order_id")
    photo = message.photo[-1]
    service = ManualPaymentService(session, notifier=NotificationService(bot=bot))
    try:
        payment = await service.submit_receipt(order_id, user.id, photo.file_id, photo.file_unique_id)
        await session.commit()
    except DuplicateReceiptError:
        await session.rollback()
        await message.answer(t("payments.transfer_err_duplicate", lang=lang))
        return
    except AlreadyPaidError:
        await session.rollback()
        await state.clear()
        await message.answer(t("payments.err_already_paid", lang=lang))
        return
    except OrderNotPayableError:
        await session.rollback()
        await state.clear()
        await message.answer(t("payments.transfer_err_not_payable", lang=lang))
        return

    await state.clear()
    await message.answer(
        t("payments.transfer_receipt_received", lang=lang),
        reply_markup=get_my_queue_keyboard(order_id, lang=lang),
    )
    await service.notify_receipt_submitted(payment.id)


@router.message(ReceiptSG.waiting_photo)
async def handle_receipt_not_a_photo(
    message: Message, state: FSMContext, session: AsyncSession, user: User, lang: str
):
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        if text.startswith("/start"):
            from aiogram.filters import CommandObject

            from app.handlers.common import handle_start
            cmd = CommandObject(prefix="/", command="start", args="")
            await handle_start(message, cmd, session, user, lang, state)
            return
        elif text.startswith("/menu"):
            from app.handlers.common import handle_menu_command
            await handle_menu_command(message, session, user)
            return

    client_buttons = [
        menu_label("client.menu_join", "uz"), menu_label("client.menu_join", "uz_cyrl"), menu_label("client.menu_join", "ru"),
        menu_label("client.menu_my_queue", "uz"), menu_label("client.menu_my_queue", "uz_cyrl"), menu_label("client.menu_my_queue", "ru"),
        menu_label("client.menu_history", "uz"), menu_label("client.menu_history", "uz_cyrl"), menu_label("client.menu_history", "ru"),
        menu_label("client.menu_lang", "uz"), menu_label("client.menu_lang", "uz_cyrl"), menu_label("client.menu_lang", "ru"),
        t("common.btn_back_main", "uz"), t("common.btn_back_main", "uz_cyrl"), t("common.btn_back_main", "ru"),
    ]
    if text in client_buttons:
        await state.clear()
        from app.handlers.common import remove_reply_markup, render_role_main_dashboard
        await remove_reply_markup(message)
        dash_text, dash_markup = await render_role_main_dashboard(session, user)
        await message.answer(dash_text, reply_markup=dash_markup, parse_mode="HTML")
        return

    await message.answer(t("payments.transfer_need_photo", lang=lang), reply_markup=get_receipt_cancel_keyboard(lang=lang))


# -------------------------------------------------------------
# My Queue & Live Tracking
# -------------------------------------------------------------
async def show_active_queue(message_or_call, session: AsyncSession, order, lang: str):
    qs = QueueService(session)
    active_orders = await qs.order_repo.get_active_orders_for_barber(order.barber_id)
    pos, ahead, wait_min = qs.calculate_order_position_and_wait(order, active_orders)

    text = t(
        "client.my_queue_title",
        lang=lang,
        ticket_no=order.ticket_no,
        barber=order.barber.display_name if order.barber else "Barber",
        service=order.service_name,
        status=order.status,
        pos=pos,
        ahead=ahead,
        wait_min=wait_min,
    )
    if order.status in (OrderStatus.WAITING.value, OrderStatus.CALLED.value):
        text += "\n" + t("client.eta_line", lang=lang, eta=QueueService.estimated_start_text(wait_min))
    markup = get_my_queue_keyboard(order.id, lang=lang)

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup)
    else:
        await message_or_call.message.edit_text(text, reply_markup=markup)


@router.message(F.text.in_([
    menu_label("client.menu_my_queue", "uz"),
    menu_label("client.menu_my_queue", "uz_cyrl"),
    menu_label("client.menu_my_queue", "ru"),
]))
@router.callback_query(F.data == "c_menu:my_queue")
async def handle_my_queue_menu(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    from app.keyboards.common import get_back_to_main_keyboard
    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    order_repo = OrderRepository(session)
    active = await order_repo.get_active_order_for_client(user.id)
    if not active:
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(t("client.no_active_queue", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        else:
            await target_msg.answer(t("client.no_active_queue", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return
    await show_active_queue(event, session, active, lang)


@router.callback_query(F.data.startswith("refresh_queue:"))
async def handle_refresh_queue(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    order_id = int(call.data.split(":")[1])
    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order or order.client_id != user.id:
        await call.answer(t("payments.err_foreign_payer", lang=lang), show_alert=True)
        return
    if order.status not in [OrderStatus.WAITING.value, OrderStatus.CALLED.value, OrderStatus.IN_SERVICE.value]:
        await call.message.edit_text(t("client.no_active_queue", lang=lang))
        return
    await show_active_queue(call, session, order, lang)
    await call.answer(t("common.refreshed", lang=lang))


@router.callback_query(F.data.startswith("cancel_queue_prompt:"))
async def handle_cancel_queue_prompt(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    order_id = int(call.data.split(":")[1])
    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order or order.client_id != user.id:
        await call.answer(t("payments.err_foreign_payer", lang=lang), show_alert=True)
        return
    prompt = t("client.cancel_confirm", lang=lang)
    markup = get_cancel_confirm_keyboard(order_id, lang=lang)
    await call.message.edit_text(prompt, reply_markup=markup)


@router.callback_query(F.data.startswith("confirm_cancel_queue:"))
async def handle_confirm_cancel_queue(
    call: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    lang: str,
):
    order_id = int(call.data.split(":")[1])
    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order or order.client_id != user.id:
        await call.answer(t("payments.err_foreign_payer", lang=lang), show_alert=True)
        return
    qs = QueueService(session, notifier=NotificationService(bot=bot))
    try:
        await qs.cancel_by_client(order_id, user.id)
        await session.commit()
        await call.message.edit_text(t("client.cancel_success", lang=lang))
    except CannotCancelInServiceError:
        await call.answer(t("client.cannot_cancel_in_service", lang=lang), show_alert=True)


@router.message(F.text.in_([
    menu_label("client.menu_history", "uz"),
    menu_label("client.menu_history", "uz_cyrl"),
    menu_label("client.menu_history", "ru"),
]))
@router.callback_query(F.data == "c_menu:history")
async def handle_client_history(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    from app.keyboards.common import get_back_to_main_keyboard
    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
        is_cb = True
    else:
        target_msg = event
        is_cb = False
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    order_repo = OrderRepository(session)
    history = await order_repo.get_client_history(user.id, limit=10)
    if not history:
        if is_cb:
            await target_msg.edit_text(t("client.history_empty", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        else:
            await target_msg.answer(t("client.history_empty", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return

    lines = [t("client.history_title", lang=lang) + "\n"]
    for o in history:
        date_str = format_datetime(o.completed_at or o.created_at)
        barber_name = o.barber.display_name if o.barber else "Barber"
        price_fmt = format_money(o.price)
        lines.append(
            t(
                "client.history_item",
                lang=lang,
                ticket_no=o.ticket_no,
                date=date_str,
                barber=barber_name,
                service=o.service_name,
                price=price_fmt,
                status=o.status,
            )
        )
    text = "\n".join(lines)
    if is_cb:
        await target_msg.edit_text(text, reply_markup=get_back_to_main_keyboard(lang))
    else:
        await target_msg.answer(text, reply_markup=get_back_to_main_keyboard(lang))


@router.callback_query(F.data == "cancel_action")
async def handle_cancel_action(call: CallbackQuery, lang: str):
    await call.message.delete()
