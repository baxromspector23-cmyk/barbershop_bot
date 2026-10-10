from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.i18n import t
from app.keyboards.barber import get_barber_main_menu, get_barber_order_actions
from app.keyboards.client import get_payment_methods_keyboard
from app.keyboards.common import get_back_to_main_keyboard, get_role_main_menu
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus, UserRole
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.notification_service import NotificationService
from app.services.payment_service import PaymentService
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
    t("barber.menu_queue", "uz"),
    t("barber.menu_queue", "uz_cyrl"),
    t("barber.menu_queue", "ru"),
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

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if not barber:
        await target_msg.answer("Barber profili topilmadi.")
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
        nick = o.client_display_name
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

    await target_msg.answer("⬅️ Bosh menyuga qaytish:", reply_markup=get_back_to_main_keyboard(lang))


# -------------------------------------------------------------
# Queue Actions: Keldi, Kelmadi, Done, Cash, Cancel
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("b_arrived:"))
async def handle_b_arrived(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        await call.answer("Permission denied", show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.client_arrived(order_id)
    await session.commit()

    if order:
        await call.answer(t("barber.arrived_success", lang=lang, ticket_no=order.ticket_no))
        await call.message.edit_reply_markup(reply_markup=get_barber_order_actions(order, lang=lang))


@router.callback_query(F.data.startswith("b_no_show:"))
async def handle_b_no_show(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        await call.answer("Permission denied", show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.handle_lateness(order_id)
    await session.commit()

    if order:
        await call.answer(t("barber.no_show_success", lang=lang, ticket_no=order.ticket_no))
        await call.message.delete()


@router.callback_query(F.data.startswith("b_done:"))
async def handle_b_done(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        await call.answer("Permission denied", show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.complete_service(order_id)
    await session.commit()

    if order:
        await call.answer(t("barber.done_success", lang=lang, ticket_no=order.ticket_no))
        await call.message.delete()

        # If order is completed and unpaid, prompt client with payment options;
        # if already paid, send thank-you/receipt only without payment keyboard
        payment_repo = PaymentRepository(session)
        payment = await payment_repo.get_by_order_id(order.id)
        if not payment or payment.status != PaymentStatus.PAID.value:
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
        await call.answer("Permission denied", show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    payment_service = PaymentService(session, notifier=NotificationService(bot=bot))
    payment = await payment_service.confirm_cash_payment(order_id, user.id)
    await session.commit()

    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    ticket_no = order.ticket_no if order else order_id
    amount_str = format_money(payment.amount)

    await call.answer(t("barber.cash_success", lang=lang, ticket_no=ticket_no, amount=amount_str), show_alert=True)
    await call.message.delete()


@router.callback_query(F.data.startswith("b_cancel:"))
async def handle_b_cancel(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_staff(user):
        await call.answer("Permission denied", show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.cancel_by_staff(order_id, user.id)
    await session.commit()

    ticket_no = order.ticket_no if order else order_id
    await call.answer(t("barber.cancel_success", lang=lang, ticket_no=ticket_no))
    await call.message.delete()


# -------------------------------------------------------------
# Toggle Status (Ishda / Dam olish)
# -------------------------------------------------------------
@router.callback_query(F.data == "b_menu:toggle_status")
async def handle_toggle_status_callback(
    call: CallbackQuery, session: AsyncSession, user: User, lang: str
):
    if not is_staff(user):
        await call.answer("Permission denied", show_alert=True)
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
    t("barber.menu_toggle_status", "uz"),
    t("barber.menu_toggle_status", "uz_cyrl"),
    t("barber.menu_toggle_status", "ru"),
]))
async def handle_toggle_status(message: Message, session: AsyncSession, user: User, lang: str):
    if not is_staff(user):
        return

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
    t("barber.menu_payments", "uz"),
    t("barber.menu_payments", "uz_cyrl"),
    t("barber.menu_payments", "ru"),
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


# -------------------------------------------------------------
# Walk-in Client (Manual client addition without Telegram)
# -------------------------------------------------------------
@router.message(F.text.in_([
    t("barber.menu_walkin", "uz"),
    t("barber.menu_walkin", "uz_cyrl"),
    t("barber.menu_walkin", "ru"),
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
            InlineKeyboardButton(
                text=f"{s.name} — {format_money(s.price)}",
                callback_data=f"walkin_svc:{s.id}",
            )
        ])
    await state.set_state(WalkinSG.waiting_for_service)
    await message.answer("Xizmatni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(WalkinSG.waiting_for_service, F.data.startswith("walkin_svc:"))
async def handle_walkin_service(
    call: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
    lang: str,
):
    svc_id = int(call.data.split(":")[1])
    data = await state.get_data()
    walkin_name = data.get("walkin_name", "Mijoz")
    walkin_phone = data.get("walkin_phone", "")

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)

    qs = QueueService(session, notifier=NotificationService(bot=bot))
    order = await qs.join_queue(
        barber_id=barber.id,
        service_id=svc_id,
        client=None,
        walkin_name=walkin_name,
        walkin_phone=walkin_phone,
        pay_now=False,
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
    t("barber.menu_services", "uz"),
    t("barber.menu_services", "uz_cyrl"),
    t("barber.menu_services", "ru"),
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

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_user_id(user.id)
    if not barber:
        return

    services = await barber_repo.get_services(barber.id, active_only=False)

    rows = []
    for s in services:
        status_icon = "🟢" if s.is_active else "🔴"
        rows.append([
            InlineKeyboardButton(
                text=f"{status_icon} {s.name} ({format_money(s.price)}, {s.duration_minutes}m)",
                callback_data=f"toggle_svc:{s.id}",
            )
        ])

    if settings.ALLOW_BARBER_EDIT_OWN_SERVICES or user.role == UserRole.OWNER.value:
        rows.append([
            InlineKeyboardButton(text=t("barber.service_add_btn", lang=lang), callback_data="add_svc_prompt")
        ])

    rows.append([
        InlineKeyboardButton(text=t("common.btn_back_main", lang=lang), callback_data="back_to_main_menu")
    ])

    title = t("barber.services_title", lang=lang)
    if is_cb:
        await target_msg.edit_text(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    else:
        await target_msg.answer(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("toggle_svc:"))
async def handle_toggle_service(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    svc_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    await barber_repo.toggle_service(svc_id)
    await session.commit()

    await call.answer("Holat yangilandi.")
    # Refresh list
    barber = await barber_repo.get_by_user_id(user.id)
    services = await barber_repo.get_services(barber.id, active_only=False)
    rows = []
    for s in services:
        status_icon = "🟢" if s.is_active else "🔴"
        rows.append([
            InlineKeyboardButton(
                text=f"{status_icon} {s.name} ({format_money(s.price)}, {s.duration_minutes}m)",
                callback_data=f"toggle_svc:{s.id}",
            )
        ])
    if settings.ALLOW_BARBER_EDIT_OWN_SERVICES or user.role == UserRole.OWNER.value:
        rows.append([
            InlineKeyboardButton(text=t("barber.service_add_btn", lang=lang), callback_data="add_svc_prompt")
        ])
    rows.append([
        InlineKeyboardButton(text=t("common.btn_back_main", lang=lang), callback_data="back_to_main_menu")
    ])
    await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "add_svc_prompt")
async def handle_add_service_prompt(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(AddServiceSG.waiting_for_name)
    await call.message.answer(t("barber.enter_service_name", lang=lang))
    await call.answer()


@router.message(AddServiceSG.waiting_for_name)
async def handle_add_svc_name(message: Message, state: FSMContext, lang: str):
    name = (message.text or "").strip()
    if not name:
        return
    await state.update_data(svc_name=name)
    await state.set_state(AddServiceSG.waiting_for_price)
    await message.answer(t("barber.enter_service_price", lang=lang))


@router.message(AddServiceSG.waiting_for_price)
async def handle_add_svc_price(message: Message, state: FSMContext, lang: str):
    text = (message.text or "").strip().replace(" ", "")
    if not text.isdigit():
        await message.answer("Iltimos, faqat raqam kiriting (masalan: 50000):")
        return
    price = int(text)
    await state.update_data(svc_price=price)
    await state.set_state(AddServiceSG.waiting_for_duration)
    await message.answer(t("barber.enter_service_duration", lang=lang))


@router.message(AddServiceSG.waiting_for_duration)
async def handle_add_svc_duration(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str
):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Iltimos, daqiqani raqamda kiriting (masalan: 30):")
        return
    duration = int(text)

    data = await state.get_data()
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

    await message.answer(t("barber.service_added", lang=lang), reply_markup=get_role_main_menu(user))
