from __future__ import annotations

import logging

from aiogram import Bot, F, Router
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
    get_services_keyboard,
)
from app.models.enums import OrderStatus, PaymentMethod
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.services.notification_service import NotificationService
from app.services.payment_service import PaymentService
from app.services.queue_service import (
    AlreadyInQueueError,
    BarberClosedError,
    CannotCancelInServiceError,
    QueueService,
)
from app.utils.formatting import format_money
from app.utils.time_utils import format_datetime

logger = logging.getLogger(__name__)
router = Router(name="client_router")


@router.message(F.text.in_([
    t("client.menu_join", "uz"),
    t("client.menu_join", "uz_cyrl"),
    t("client.menu_join", "ru"),
]))
@router.callback_query(F.data == "c_menu:join")
async def handle_join_queue_menu(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event

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
            if qs.is_barber_open(b, wait_min):
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
    )
    markup = get_payment_timing_keyboard(barber_id, service_id, lang=lang)
    await call.message.edit_text(confirm_text, reply_markup=markup)


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
        )
        markup = get_my_queue_keyboard(order.id, lang=lang)
        await call.message.edit_text(success_msg, reply_markup=markup)


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
    markup = get_my_queue_keyboard(order.id, lang=lang)

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=markup)
    else:
        await message_or_call.message.edit_text(text, reply_markup=markup)


@router.message(F.text.in_([
    t("client.menu_my_queue", "uz"),
    t("client.menu_my_queue", "uz_cyrl"),
    t("client.menu_my_queue", "ru"),
]))
@router.callback_query(F.data == "c_menu:my_queue")
async def handle_my_queue_menu(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    from app.keyboards.common import get_back_to_main_keyboard
    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event

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
    t("client.menu_history", "uz"),
    t("client.menu_history", "uz_cyrl"),
    t("client.menu_history", "ru"),
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
