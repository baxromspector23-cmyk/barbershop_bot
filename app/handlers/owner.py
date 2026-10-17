import html
import logging
import re
from datetime import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.handlers.barber import AddServiceSG
from app.i18n import t
from app.keyboards.common import btn, get_back_to_main_keyboard, menu_label
from app.keyboards.owner import (
    get_refund_action_keyboard,
    get_reports_keyboard,
)
from app.models.barber import Barber
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.user_repo import UserRepository
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService
from app.services.report_service import ReportService
from app.services.site_admin_service import (
    apply_new_site_password,
    generate_secure_password,
    get_current_password_display,
)
from app.services.user_service import UserService
from app.utils.formatting import format_money
from app.utils.time_utils import get_day_bounds_utc, get_week_bounds_utc, tashkent_today

logger = logging.getLogger(__name__)
router = Router(name="owner_router")


class BlockUserSG(StatesGroup):
    waiting_for_query = State()


class AdminSiteSG(StatesGroup):
    waiting_for_new_site_password = State()


class EditScheduleSG(StatesGroup):
    waiting_for_hours = State()


def is_owner(user: User) -> bool:
    return user.role == UserRole.OWNER.value


# -------------------------------------------------------------
# Live Overview of All Queues
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("owner.menu_all_queues", "uz"),
    menu_label("owner.menu_all_queues", "uz_cyrl"),
    menu_label("owner.menu_all_queues", "ru"),
]))
@router.callback_query(F.data == "o_menu:all_queues")
async def handle_all_queues(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    barber_repo = BarberRepository(session)
    qs = QueueService(session)
    barbers = await barber_repo.get_all()

    lines = [t("owner.all_queues_title", lang=lang)]
    for b in barbers:
        q_len, wait_min = await qs.get_barber_queue_metrics(b.id)
        status = t("barber.status_paused", lang=lang) if b.is_paused else t("barber.status_active", lang=lang)
        lines.append(
            t(
                "owner.queue_item_barber",
                lang=lang,
                name=b.display_name,
                status=status,
                count=q_len,
                wait=wait_min,
            )
        )

    await target_msg.answer("".join(lines), reply_markup=get_back_to_main_keyboard(lang))


# -------------------------------------------------------------
# Katta Barber Info: Clients with Phones & Payment Receipts
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("owner.menu_info", "uz"),
    menu_label("owner.menu_info", "uz_cyrl"),
    menu_label("owner.menu_info", "ru"),
]))
@router.callback_query(F.data == "o_menu:info")
async def handle_owner_info_menu(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    user_repo = UserRepository(session)
    payment_repo = PaymentRepository(session)

    total_clients = await user_repo.count_clients()
    recent_clients = await user_repo.get_all_clients(limit=10)
    pending_receipts = await payment_repo.get_pending_receipts()
    recent_receipts = await payment_repo.get_recent_transfer_payments(limit=5)

    client_lines = []
    if recent_clients:
        for idx, c in enumerate(recent_clients, 1):
            phone = c.phone or t("common.not_entered", lang=lang)
            client_lines.append(f"{idx}. 👤 <b>{html.escape(c.display_nick)}</b>: 📱 <code>{html.escape(phone)}</code>")
    else:
        client_lines.append(f"<i>{t('owner.info_no_clients', lang=lang)}</i>")

    receipt_lines = []
    if recent_receipts:
        for p in recent_receipts:
            ticket = f"#{p.order.ticket_no}" if p.order else f"ID:{p.id}"
            nick = p.order.client_display_name if p.order else (p.client.display_nick if p.client else "Mijoz")
            phone = p.client.phone if p.client and p.client.phone else ""
            phone_str = f" ({html.escape(phone)})" if phone else ""
            status_icon = "✅" if p.status == "PAID" else ("⏳" if p.status == "RECEIPT_SENT" else "❌")
            status_key = f"payments.status_{p.status.lower()}"
            status_name = t(status_key, lang=lang)
            receipt_lines.append(
                f"🧾 <b>{html.escape(ticket)}</b> — {html.escape(nick)}{phone_str}: {format_money(p.amount)} so'm [{status_icon} {status_name}]"
            )
    else:
        receipt_lines.append(f"<i>{t('owner.info_no_receipts', lang=lang)}</i>")

    text = t(
        "owner.info_panel_text",
        lang=lang,
        total_clients=total_clients,
        pending_count=len(pending_receipts),
        clients_block="\n".join(client_lines),
        receipts_block="\n".join(receipt_lines),
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(text=t("owner.btn_pending_receipts_count", lang=lang, count=len(pending_receipts)), callback_data="b_menu:pending_receipts", icon="receipt"),
            ],
            [
                btn(text=t("owner.btn_all_clients", lang=lang), callback_data="o_clients:1", icon="users"),
            ],
            [
                btn(text=t("common.back_btn", lang=lang), callback_data="back_to_main_menu", icon="back"),
            ],
        ]
    )
    if isinstance(event, CallbackQuery) and target_msg:
        try:
            await target_msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await target_msg.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("o_clients:"))
async def handle_owner_clients_list(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    page = int(call.data.split(":")[1])
    per_page = 10
    offset = (page - 1) * per_page

    user_repo = UserRepository(session)
    total_clients = await user_repo.count_clients()
    clients = await user_repo.get_all_clients(limit=per_page, offset=offset)

    title_line = t("owner.clients_list_title", lang=lang, total=total_clients)
    lines = [title_line]
    for idx, c in enumerate(clients, offset + 1):
        phone = c.phone or t("common.not_entered", lang=lang)
        lines.append(f"{idx}. 👤 <b>{html.escape(c.display_nick)}</b>\n   📱 <code>{html.escape(phone)}</code> | ID: {c.telegram_id}")

    nav_btns = []
    if page > 1:
        nav_btns.append(btn(text=t("owner.btn_prev_page", lang=lang), callback_data=f"o_clients:{page - 1}", icon="back"))
    if offset + per_page < total_clients:
        nav_btns.append(btn(text=t("owner.btn_next_page", lang=lang), callback_data=f"o_clients:{page + 1}", icon="next"))

    rows = []
    if nav_btns:
        rows.append(nav_btns)
    rows.append([
        btn(text=t("common.back_btn", lang=lang), callback_data="o_menu:info", icon="back"),
    ])

    await call.message.edit_text("\n\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await call.answer()


# -------------------------------------------------------------
# Barbers Management & Invite Generation
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("owner.menu_barbers", "uz"),
    menu_label("owner.menu_barbers", "uz_cyrl"),
    menu_label("owner.menu_barbers", "ru"),
]))
@router.callback_query(F.data == "o_menu:barbers")
async def handle_barbers_list(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
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
    barbers = await barber_repo.get_all()

    text = t("owner.barber_list_title", lang=lang) + "\n"
    buttons = []
    for b in barbers:
        active_str = "🟢" if b.is_active else "🔴"
        paused_str = t("owner.status_paused", lang=lang) if b.is_paused else ""
        text += f"\n{active_str} #{b.id} {b.display_name}{paused_str}"
        icon_name = "green" if b.is_active else "red"
        buttons.append([
            btn(
                text=f"{active_str} {b.display_name}",
                callback_data=f"owner_manage_barber:{b.id}",
                icon=icon_name,
            )
        ])

    buttons.append([
        btn(
            text=t("owner.btn_invite_barber", lang=lang),
            callback_data="create_barber_invite",
            icon="plus",
        )
    ])
    buttons.append([
        btn(
            text=t("common.btn_back_main", lang=lang),
            callback_data="back_to_main_menu",
            icon="home",
        )
    ])
    if is_cb:
        await target_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await target_msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def render_barber_management_card(
    session: AsyncSession, barber: Barber, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    qs = QueueService(session)
    payment_repo = PaymentRepository(session)
    q_len, wait_min = await qs.get_barber_queue_metrics(barber.id)

    today = tashkent_today()
    day_start, day_end = get_day_bounds_utc(today)
    week_start, week_end = get_week_bounds_utc(today)

    today_rev = await payment_repo.get_barber_revenue_in_range(barber.id, day_start, day_end)
    week_rev = await payment_repo.get_barber_revenue_in_range(barber.id, week_start, week_end)

    status_str = t("owner.status_active", lang=lang) if barber.is_active else t("owner.status_inactive", lang=lang)
    paused_str = t("owner.status_paused", lang=lang) if barber.is_paused else ""
    username_str = f"@{barber.user.username}" if barber.user and barber.user.username else "—"
    phone_str = barber.user.phone if (barber.user and barber.user.phone and barber.user.phone != "Kiritilmagan") else t("common.not_entered", lang=lang)

    text = t(
        "owner.barber_card",
        lang=lang,
        name=barber.display_name,
        username=username_str,
        phone=phone_str,
        status=status_str,
        paused=paused_str,
        count=q_len,
        wait=wait_min,
        today_rev=format_money(today_rev),
        week_rev=format_money(week_rev),
    )

    toggle_btn_text = t("owner.btn_deactivate", lang=lang) if barber.is_active else t("owner.btn_activate", lang=lang)
    toggle_icon = "red" if barber.is_active else "green"
    buttons = [
        [
            btn(text=toggle_btn_text, callback_data=f"owner_toggle_barber_active:{barber.id}", icon=toggle_icon),
            btn(text=t("owner.btn_barber_services", lang=lang), callback_data=f"owner_barber_services:{barber.id}", icon="scissors"),
        ],
    ]
    if barber.user and barber.user.role == UserRole.BARBER.value:
        buttons.append([
            btn(text=t("owner.btn_revoke_admin", lang=lang), callback_data=f"owner_revoke_admin:{barber.id}", icon="user")
        ])
    buttons.append([
        btn(text=t("owner.btn_back_to_barbers", lang=lang), callback_data="owner_back_to_barbers", icon="back")
    ])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("owner_manage_barber:"))
async def handle_owner_manage_barber(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    barber_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_id(barber_id)
    if not barber:
        await call.answer(t("common.barber_not_found", lang=lang), show_alert=True)
        return

    text, markup = await render_barber_management_card(session, barber, lang)
    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("owner_toggle_barber_active:"))
async def handle_owner_toggle_barber_active(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    barber_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_id(barber_id)
    if not barber:
        return

    await barber_repo.set_active(barber.id, not barber.is_active)
    await session.commit()
    await call.answer(t("owner.barber_status_updated", lang=lang))

    barber = await barber_repo.get_by_id(barber_id)
    text, markup = await render_barber_management_card(session, barber, lang)
    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("owner_revoke_admin:"))
async def handle_owner_revoke_admin(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    barber_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_id(barber_id)
    if not barber:
        return

    if barber.user_id == user.id:
        await call.answer(t("owner.cannot_revoke_self", lang=lang), show_alert=True)
        return

    if barber.user:
        barber.user.role = UserRole.CLIENT.value
    barber.is_active = False
    await session.commit()
    await call.answer(t("owner.admin_revoked", lang=lang), show_alert=True)

    text, markup = await render_barber_management_card(session, barber, lang)
    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


def get_weekday_name(weekday: int, lang: str) -> str:
    return t(f"common.weekday_{weekday}", lang=lang)


async def render_barber_schedule_view(
    session: AsyncSession, barber: Barber, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    barber_repo = BarberRepository(session)
    wh_list = await barber_repo.get_working_hours(barber.id)
    wh_map = {wh.weekday: wh for wh in wh_list}

    lines = []
    if not settings.CHECK_WORKING_HOURS:
        lines.append(t("owner.hours_not_enforced_banner", lang=lang) + "\n")
    lines.append(t("owner.schedule_view_title", lang=lang, name=html.escape(barber.display_name)))
    buttons = []
    for day_idx in range(7):
        day_name = get_weekday_name(day_idx, lang=lang)
        wh = wh_map.get(day_idx)
        is_off = bool(wh and wh.is_day_off)
        if is_off:
            status_text = t("owner.schedule_day_off", lang=lang)
            btn_text = f"🔴 {day_name}: {t('owner.schedule_day_off_btn', lang=lang)}"
        elif wh:
            status_text = _format_hours(wh)
            btn_text = f"🟢 {day_name}: {status_text}"
        else:
            status_text = "00:00 - 24:00"
            btn_text = f"🟢 {day_name}: {status_text}"
        icon_name = "red" if is_off else "green"
        lines.append(t("owner.schedule_item", lang=lang, day=day_name, status=status_text))
        buttons.append([
            btn(
                text=btn_text,
                callback_data=f"owner_edit_wh:{barber.id}:{day_idx}",
                icon=icon_name,
            )
        ])

    buttons.append([
        btn(
            text=t("owner.btn_back_to_barber_info", lang=lang),
            callback_data=f"owner_manage_barber:{barber.id}",
            icon="back",
        )
    ])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


def _format_hours(wh) -> str:
    if wh.start_time == wh.end_time:
        return "00:00 - 24:00"
    return f"{wh.start_time.strftime('%H:%M')} - {wh.end_time.strftime('%H:%M')}"


@router.callback_query(F.data.startswith("owner_barber_schedule:"))
async def handle_owner_barber_schedule(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    barber_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_id(barber_id)
    if not barber:
        return

    text, markup = await render_barber_schedule_view(session, barber, lang)
    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("owner_edit_wh:"))
async def handle_owner_edit_wh(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    _, barber_id_str, weekday_str = call.data.split(":")
    barber_id, weekday = int(barber_id_str), int(weekday_str)

    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_id(barber_id)
    wh = await barber_repo.get_working_hour(barber_id, weekday)
    if not barber:
        return

    day_name = get_weekday_name(weekday, lang=lang)
    if wh and wh.is_day_off:
        status_desc = t("owner.schedule_day_off", lang=lang)
    elif wh:
        status_desc = _format_hours(wh)
    else:
        status_desc = "00:00 - 24:00"

    banner = (t("owner.hours_not_enforced_banner", lang=lang) + "\n\n") if not settings.CHECK_WORKING_HOURS else ""
    text = banner + t(
        "owner.day_detail_title",
        lang=lang,
        name=html.escape(barber.display_name),
        day=day_name,
        status=status_desc,
    )
    toggle_text = t("owner.btn_make_workday", lang=lang) if (wh and wh.is_day_off) else t("owner.btn_make_dayoff", lang=lang)
    toggle_icon = "green" if (wh and wh.is_day_off) else "red"
    buttons = [
        [
            btn(text=toggle_text, callback_data=f"owner_toggle_dayoff:{barber_id}:{weekday}", icon=toggle_icon),
            btn(text=t("owner.btn_change_hours", lang=lang), callback_data=f"owner_set_hours_prompt:{barber_id}:{weekday}", icon="edit"),
        ],
        [
            btn(text=t("owner.btn_back_to_schedule", lang=lang), callback_data=f"owner_barber_schedule:{barber_id}", icon="back"),
        ],
    ]
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("owner_toggle_dayoff:"))
async def handle_owner_toggle_dayoff(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    _, barber_id_str, weekday_str = call.data.split(":")
    barber_id, weekday = int(barber_id_str), int(weekday_str)

    barber_repo = BarberRepository(session)
    wh = await barber_repo.get_working_hour(barber_id, weekday)
    new_day_off = not (wh.is_day_off if wh else False)
    await barber_repo.update_working_hours(barber_id, weekday, is_day_off=new_day_off)
    await session.commit()
    await call.answer(t("owner.day_status_updated", lang=lang))

    barber = await barber_repo.get_by_id(barber_id)
    text, markup = await render_barber_schedule_view(session, barber, lang)
    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("owner_set_hours_prompt:"))
async def handle_owner_set_hours_prompt(call: CallbackQuery, state: FSMContext, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    _, barber_id_str, weekday_str = call.data.split(":")
    barber_id, weekday = int(barber_id_str), int(weekday_str)

    await state.set_state(EditScheduleSG.waiting_for_hours)
    await state.update_data(target_barber_id=barber_id, target_weekday=weekday)
    day_name = get_weekday_name(weekday, lang=lang)
    prompt = t("owner.prompt_enter_hours", lang=lang, day=day_name)
    await call.message.answer(prompt)
    await call.answer()


@router.message(EditScheduleSG.waiting_for_hours)
async def handle_submit_working_hours(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str
):
    if user.role != UserRole.OWNER.value and user.role != UserRole.BARBER.value:
        await state.clear()
        return

    text = (message.text or "").strip()
    data = await state.get_data()
    barber_id = data.get("target_barber_id")
    weekday = data.get("target_weekday")

    if text.lower() in ["24", "24/7", "24 soat", "24ч"]:
        start_t = time(0, 0)
        end_t = time(0, 0)
    else:
        pattern = r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])\s*-\s*([0-1]?[0-9]|2[0-4]):([0-5][0-9])$"
        match = re.match(pattern, text)
        if not match:
            await message.answer(t("owner.err_time_format", lang=lang))
            return

        h1, m1, h2, m2 = map(int, match.groups())
        if (h1 == 0 and m1 == 0 and h2 == 24 and m2 == 0) or (h1 == 0 and m1 == 0 and h2 == 0 and m2 == 0):
            start_t = time(0, 0)
            end_t = time(0, 0)
        else:
            if h2 == 24:
                h2 = 23
                m2 = 59
            start_t = time(h1, m1)
            end_t = time(h2, m2)
            if start_t >= end_t:
                await message.answer(t("owner.err_time_order", lang=lang))
                return

    barber_repo = BarberRepository(session)
    await barber_repo.update_working_hours(
        barber_id=barber_id,
        weekday=weekday,
        start_time=start_t,
        end_time=end_t,
        is_day_off=False,
    )
    await session.commit()
    await state.clear()

    barber = await barber_repo.get_by_id(barber_id)
    text_view, markup = await render_barber_schedule_view(session, barber, lang)
    msg_text = t("owner.hours_saved", lang=lang, text_view=text_view)
    await message.answer(msg_text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data == "owner_back_to_barbers")
async def handle_owner_back_to_barbers(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        return
    barber_repo = BarberRepository(session)
    barbers = await barber_repo.get_all()

    text = t("owner.barber_list_title", lang=lang) + "\n"
    buttons = []
    for b in barbers:
        active_str = "🟢" if b.is_active else "🔴"
        paused_str = t("owner.status_paused", lang=lang) if b.is_paused else ""
        text += f"\n{active_str} #{b.id} {b.display_name}{paused_str}"
        icon_name = "green" if b.is_active else "red"
        buttons.append([
            btn(
                text=f"{active_str} {b.display_name}",
                callback_data=f"owner_manage_barber:{b.id}",
                icon=icon_name,
            )
        ])

    buttons.append([
        btn(
            text=t("owner.btn_invite_barber", lang=lang),
            callback_data="create_barber_invite",
            icon="plus",
        )
    ])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@router.callback_query(F.data == "create_barber_invite")
async def handle_create_barber_invite(call: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    user_service = UserService(session)
    invite, raw_token = await user_service.create_barber_invite(creator_user_id=user.id)
    await session.commit()

    bot_info = await bot.get_me()
    deep_link = f"https://t.me/{bot_info.username}?start=barber_{raw_token}"
    msg = t("owner.invite_link_created", lang=lang, link=deep_link)
    await call.message.answer(msg)
    await call.answer()


# -------------------------------------------------------------
# Services Management (Any Barber)
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("owner.menu_services", "uz"),
    menu_label("owner.menu_services", "uz_cyrl"),
    menu_label("owner.menu_services", "ru"),
]))
@router.callback_query(F.data == "o_menu:services")
async def handle_owner_services_menu(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
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
    barbers = await barber_repo.get_all()
    if not barbers:
        if is_cb:
            await target_msg.edit_text(t("owner.no_barbers", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        else:
            await target_msg.answer(t("owner.no_barbers", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return

    rows = []
    for b in barbers:
        rows.append([
            btn(
                text=f"💈 {b.display_name}",
                callback_data=f"owner_barber_services:{b.id}",
                icon="barbershop",
            )
        ])
    rows.append([
        btn(
            text=t("common.btn_back_main", lang=lang),
            callback_data="back_to_main_menu",
            icon="home",
        )
    ])
    prompt = t("owner.select_barber_services", lang=lang)
    if is_cb:
        await target_msg.edit_text(prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    else:
        await target_msg.answer(prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("owner_barber_services:"))
async def handle_owner_barber_services(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    barber_id = int(call.data.split(":")[1])
    barber_repo = BarberRepository(session)
    barber = await barber_repo.get_by_id(barber_id)
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
    rows.append([
        btn(
            text=t("barber.service_add_btn", lang=lang),
            callback_data=f"owner_add_svc:{barber.id}",
            icon="plus",
        )
    ])
    hint = t("owner.barber_services_hint", lang=lang)
    header_text = t("owner.barber_services_header", lang=lang, name=barber.display_name, hint=hint)
    await call.message.edit_text(
        header_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("owner_add_svc:"))
async def handle_owner_add_svc(call: CallbackQuery, state: FSMContext, user: User, lang: str):
    if not is_owner(user):
        return

    barber_id = int(call.data.split(":")[1])
    await state.set_state(AddServiceSG.waiting_for_name)
    await state.update_data(target_barber_id=barber_id)
    await call.message.answer(t("barber.enter_service_name", lang=lang))
    await call.answer()


# -------------------------------------------------------------
# Reports (Today / Week / Month, Navigation, CSV)
# -------------------------------------------------------------
async def render_report_view(
    session: AsyncSession, period_type: str, offset: int, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    report_service = ReportService(session)
    summary = await report_service.generate_report(period_type, offset)

    ranking_lines = []
    for idx, r in enumerate(summary.rankings, 1):
        crown = "👑 " if r.is_top else ""
        rev_fmt = format_money(r.revenue)
        ranking_lines.append(f"{crown}{idx}. {r.display_name}: {rev_fmt} ({r.services_count} ta)")

    ranking_text = "\n".join(ranking_lines) if ranking_lines else t("owner.report_no_services", lang=lang)

    text = t(
        "owner.reports_title",
        lang=lang,
        period=summary.period_title,
        total_revenue=format_money(summary.total_revenue),
        total_services=summary.total_services,
        payme_sum=format_money(summary.payme_sum),
        click_sum=format_money(summary.click_sum),
        paynet_sum=format_money(summary.paynet_sum),
        cash_sum=format_money(summary.cash_sum),
        ranking=ranking_text,
    )
    markup = get_reports_keyboard(period_type, offset, lang=lang)
    return text, markup


@router.message(F.text.in_([
    menu_label("owner.menu_reports", "uz"),
    menu_label("owner.menu_reports", "uz_cyrl"),
    menu_label("owner.menu_reports", "ru"),
]))
@router.callback_query(F.data == "o_menu:reports")
async def handle_reports_menu(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
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

    text, markup = await render_report_view(session, "today", 0, lang)
    if is_cb:
        await target_msg.edit_text(text, reply_markup=markup)
    else:
        await target_msg.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("rep:"))
async def handle_report_nav(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    _, period_type, offset_str = call.data.split(":")
    offset = int(offset_str)

    text, markup = await render_report_view(session, period_type, offset, lang)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("rep_csv:"))
async def handle_report_csv(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    _, period_type, offset_str = call.data.split(":")
    offset = int(offset_str)

    report_service = ReportService(session)
    csv_content = await report_service.generate_csv(period_type, offset)
    _, _, title = report_service.get_period_bounds(period_type, offset)

    filename = f"report_{period_type}_{title.replace(' ', '_')}.csv"
    file_bytes = csv_content.encode("utf-8-sig")  # utf-8 with BOM for Excel compatibility

    await call.message.answer_document(
        document=BufferedInputFile(file_bytes, filename=filename),
        caption=t("owner.report_csv_caption", lang=lang, title=title),
    )
    await call.answer()


# -------------------------------------------------------------
# Refunds (Pending Manual Refunds)
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("owner.menu_refunds", "uz"),
    menu_label("owner.menu_refunds", "uz_cyrl"),
    menu_label("owner.menu_refunds", "ru"),
]))
@router.callback_query(F.data == "o_menu:refunds")
async def handle_refunds_menu(event: Message | CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    payment_repo = PaymentRepository(session)
    pending_refunds = await payment_repo.get_refund_pending_payments()
    if not pending_refunds:
        await target_msg.answer(t("owner.refunds_empty", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return

    await target_msg.answer(t("owner.refunds_title", lang=lang))
    for p in pending_refunds:
        barber_name = p.barber.display_name if p.barber else "Barber"
        nick = p.order.display_name_for(user) if p.order else (f"{p.client.display_nick} ({p.client.phone})" if p.client and p.client.phone else "Mijoz")
        text = t(
            "owner.refund_item",
            lang=lang,
            id=p.id,
            nick=nick,
            amount=format_money(p.amount),
            method=p.method,
            barber=barber_name,
        )
        markup = get_refund_action_keyboard(p.id, lang=lang)
        await target_msg.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("mark_refunded:"))
async def handle_mark_refunded(call: CallbackQuery, session: AsyncSession, user: User, lang: str):
    if not is_owner(user):
        await call.answer(t("barber.permission_denied", lang=lang), show_alert=True)
        return

    payment_id = int(call.data.split(":")[1])
    payment_service = PaymentService(session)
    await payment_service.mark_refund_done(payment_id, user.id)
    await session.commit()

    await call.answer(t("owner.refund_done", lang=lang), show_alert=True)
    await call.message.delete()


# -------------------------------------------------------------
# Client Block / Unblock
# -------------------------------------------------------------
@router.message(F.text.in_([
    menu_label("owner.menu_block", "uz"),
    menu_label("owner.menu_block", "uz_cyrl"),
    menu_label("owner.menu_block", "ru"),
]))
@router.callback_query(F.data == "o_menu:block")
async def handle_block_menu(event: Message | CallbackQuery, state: FSMContext, user: User, lang: str):
    if not is_owner(user):
        return

    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event
        from app.handlers.common import remove_reply_markup
        await remove_reply_markup(target_msg)

    await state.set_state(BlockUserSG.waiting_for_query)
    await target_msg.answer(t("owner.block_prompt", lang=lang), reply_markup=get_back_to_main_keyboard(lang))


@router.message(BlockUserSG.waiting_for_query)
async def handle_block_query(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str
):
    query = (message.text or "").strip()
    user_service = UserService(session)
    result = await user_service.toggle_client_block(user.id, query)
    await session.commit()
    await state.clear()

    if not result:
        await message.answer(t("owner.user_not_found", lang=lang))
        return

    target_user, is_now_blocked = result
    nick = target_user.display_nick
    if is_now_blocked:
        await message.answer(t("owner.client_blocked_msg", lang=lang, nick=nick))
    else:
        await message.answer(t("owner.client_unblocked_msg", lang=lang, nick=nick))


# -------------------------------------------------------------
# Katta Barber: /admin Website & Credentials Management
# -------------------------------------------------------------
def get_admin_panel_content() -> tuple[str, InlineKeyboardMarkup]:
    site_url = f"{settings.SITE_BASE_URL.rstrip('/')}/login"
    login_user = settings.SITE_USERNAME
    cur_pwd = get_current_password_display()

    text = (
        "👑 <b>KATTA BARBER — SAYT BOSHQARUV PANELI</b>\n\n"
        f"🌐 <b>Sayt manzili (URL):</b>\n<code>{site_url}</code>\n\n"
        f"👤 <b>Login:</b> <code>{login_user}</code>\n"
        f"🔑 <b>Joriy parol:</b> <code>{cur_pwd}</code>\n\n"
        "💡 <i>Saytda barcha mijozlar bazasi, telefon raqamlari va to'lov kvitansiyalari mavjud.\n\n"
        "Agar parolni unutgan bo'lsangiz yoki yangilamoqchi bo'lsangiz, quyidagi tugmalardan birini bosing:</i>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Saytga o'tish (Login)", url=site_url)],
            [
                InlineKeyboardButton(
                    text="🔄 Yangi parol generatsiya qilish",
                    callback_data="admin_site:gen_pwd",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ O'zim yangi parol yozaman",
                    callback_data="admin_site:set_pwd",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Yopish",
                    callback_data="admin_site:close",
                ),
            ],
        ]
    )
    return text, kb


@router.message(Command("admin"))
async def handle_admin_command(message: Message, user: User, lang: str):
    if not (is_owner(user) or (message.from_user and message.from_user.id in settings.OWNER_TELEGRAM_IDS)):
        await message.answer("⛔ Kechirasiz, bu buyruq faqat katta barber (rahbar) uchun mo'ljallangan.")
        return

    text, kb = get_admin_panel_content()
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data == "admin_site:panel")
async def handle_admin_panel_return(call: CallbackQuery, user: User):
    if not (is_owner(user) or (call.from_user and call.from_user.id in settings.OWNER_TELEGRAM_IDS)):
        await call.answer("Ruxsat berilmagan!", show_alert=True)
        return

    text, kb = get_admin_panel_content()
    try:
        await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await call.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data == "admin_site:close")
async def handle_admin_panel_close(call: CallbackQuery, user: User):
    if not (is_owner(user) or (call.from_user and call.from_user.id in settings.OWNER_TELEGRAM_IDS)):
        await call.answer()
        return

    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == "admin_site:cancel")
async def handle_admin_panel_cancel(call: CallbackQuery, state: FSMContext, user: User):
    if not (is_owner(user) or (call.from_user and call.from_user.id in settings.OWNER_TELEGRAM_IDS)):
        await call.answer()
        return

    await state.clear()
    text, kb = get_admin_panel_content()
    try:
        await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await call.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    await call.answer("Bekor qilindi")


@router.callback_query(F.data == "admin_site:gen_pwd")
async def handle_admin_generate_password(call: CallbackQuery, user: User):
    if not (is_owner(user) or (call.from_user and call.from_user.id in settings.OWNER_TELEGRAM_IDS)):
        await call.answer("Ruxsat berilmagan!", show_alert=True)
        return

    new_pwd = generate_secure_password()
    ok, msg = await apply_new_site_password(new_pwd)
    if not ok:
        await call.answer(f"Xatolik: {msg}", show_alert=True)
        return

    site_url = f"{settings.SITE_BASE_URL.rstrip('/')}/login"
    text = (
        "✅ <b>Yangi sayt paroli muvaffaqiyatli yaratildi va o'rnatildi!</b>\n\n"
        f"🌐 <b>Sayt manzili:</b> <code>{site_url}</code>\n"
        f"👤 <b>Login:</b> <code>{settings.SITE_USERNAME}</code>\n"
        f"🔑 <b>Yangi parol:</b> <code>{new_pwd}</code>\n\n"
        "⚠️ <b>Muhim:</b> <i>Ushbu parolni nusxalab oling (ustiga bossangiz nusxalanadi). Yangi parol darhol saytda va serverda faollashdi!</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Saytni ochish", url=site_url)],
            [InlineKeyboardButton(text="🔙 Boshqaruv paneliga qaytish", callback_data="admin_site:panel")],
        ]
    )
    try:
        await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await call.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    await call.answer("Yangi parol o'rnatildi!", show_alert=True)


@router.callback_query(F.data == "admin_site:set_pwd")
async def handle_admin_set_password_prompt(call: CallbackQuery, state: FSMContext, user: User):
    if not (is_owner(user) or (call.from_user and call.from_user.id in settings.OWNER_TELEGRAM_IDS)):
        await call.answer("Ruxsat berilmagan!", show_alert=True)
        return

    await state.set_state(AdminSiteSG.waiting_for_new_site_password)
    text = (
        "✏️ <b>Yangi sayt parolini yozib yuboring:</b>\n\n"
        "<i>Talablar: kamida 8 ta belgidan iborat bo'lsin.</i>\n\n"
        "🔒 <b>Xavfsizlik kafolati:</b> Siz yozgan xabar bot tomonidan darhol o'chirib yuboriladi, chat tarixida qolmaydi."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_site:cancel")],
        ]
    )
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.message(AdminSiteSG.waiting_for_new_site_password)
async def handle_admin_receive_new_password(message: Message, state: FSMContext, user: User):
    if not (is_owner(user) or (message.from_user and message.from_user.id in settings.OWNER_TELEGRAM_IDS)):
        return

    # Delete owner message immediately so password is never retained in Telegram chat
    try:
        await message.delete()
    except Exception:
        pass

    new_pwd = (message.text or "").strip()
    if len(new_pwd) < 8:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_site:cancel")],
            ]
        )
        await message.answer(
            "⚠️ <b>Parol juda qisqa!</b> Kamida 8 ta belgidan iborat bo'lishi kerak.\nQaytadan kiriting:",
            reply_markup=kb,
        )
        return

    ok, msg = await apply_new_site_password(new_pwd)
    if not ok:
        await message.answer(f"❌ Xatolik yuz berdi: {msg}")
        return

    await state.clear()
    site_url = f"{settings.SITE_BASE_URL.rstrip('/')}/login"
    text = (
        "✅ <b>Yangi sayt paroli muvaffaqiyatli qabul qilindi va o'rnatildi!</b>\n\n"
        f"🌐 <b>Sayt manzili:</b> <code>{site_url}</code>\n"
        f"👤 <b>Login:</b> <code>{settings.SITE_USERNAME}</code>\n"
        f"🔑 <b>O'rnatilgan yangi parol:</b> <code>{new_pwd}</code>\n\n"
        "⚠️ <i>Parol saytda va serverda faollashtirildi. Xavfsiz joyga saqlab qo'ying!</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Saytga o'tish", url=site_url)],
            [InlineKeyboardButton(text="👑 Boshqaruv paneli", callback_data="admin_site:panel")],
        ]
    )
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
