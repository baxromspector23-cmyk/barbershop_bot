import logging
import re
from datetime import time

from aiogram import Bot, F, Router
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

from app.handlers.barber import AddServiceSG
from app.i18n import t
from app.keyboards.common import get_back_to_main_keyboard
from app.keyboards.owner import (
    get_refund_action_keyboard,
    get_reports_keyboard,
)
from app.models.barber import Barber
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService
from app.services.report_service import ReportService
from app.services.user_service import UserService
from app.utils.formatting import format_money
from app.utils.time_utils import get_day_bounds_utc, get_week_bounds_utc, tashkent_today

logger = logging.getLogger(__name__)
router = Router(name="owner_router")


class BlockUserSG(StatesGroup):
    waiting_for_query = State()


class EditScheduleSG(StatesGroup):
    waiting_for_hours = State()


def is_owner(user: User) -> bool:
    return user.role == UserRole.OWNER.value


# -------------------------------------------------------------
# Live Overview of All Queues
# -------------------------------------------------------------
@router.message(F.text.in_([
    t("owner.menu_all_queues", "uz"),
    t("owner.menu_all_queues", "uz_cyrl"),
    t("owner.menu_all_queues", "ru"),
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
# Barbers Management & Invite Generation
# -------------------------------------------------------------
@router.message(F.text.in_([
    t("owner.menu_barbers", "uz"),
    t("owner.menu_barbers", "uz_cyrl"),
    t("owner.menu_barbers", "ru"),
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

    barber_repo = BarberRepository(session)
    barbers = await barber_repo.get_all()

    text = t("owner.barber_list_title", lang=lang) + "\n"
    buttons = []
    for b in barbers:
        active_str = "🟢" if b.is_active else "🔴"
        paused_str = " (Dam olishda)" if b.is_paused else ""
        text += f"\n{active_str} #{b.id} {b.display_name}{paused_str}"
        buttons.append([
            InlineKeyboardButton(
                text=f"{active_str} {b.display_name}",
                callback_data=f"owner_manage_barber:{b.id}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text=t("owner.btn_invite_barber", lang=lang),
            callback_data="create_barber_invite",
        )
    ])
    buttons.append([
        InlineKeyboardButton(
            text=t("common.btn_back_main", lang=lang),
            callback_data="back_to_main_menu",
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

    status_str = "🟢 Faol" if barber.is_active else "🔴 Faol emas"
    paused_str = " (Dam olishda)" if barber.is_paused else ""
    username_str = f"@{barber.user.username}" if barber.user and barber.user.username else "—"
    phone_str = barber.user.phone if barber.user and barber.user.phone else "—"

    text = (
        f"💈 <b>{barber.display_name}</b>\n"
        f"Username: {username_str}\n"
        f"Telefon: {phone_str}\n"
        f"Holati: {status_str}{paused_str}\n"
        f"Navbat: {q_len} ta mijoz (~{wait_min} daq)\n"
        f"Bugungi tushum: {format_money(today_rev)}\n"
        f"Haftalik tushum: {format_money(week_rev)}"
    )

    toggle_btn_text = "🔴 O'chirish" if barber.is_active else "🟢 Faollashtirish"
    buttons = [
        [
            InlineKeyboardButton(text=toggle_btn_text, callback_data=f"owner_toggle_barber_active:{barber.id}"),
            InlineKeyboardButton(text="✂️ Xizmatlari", callback_data=f"owner_barber_services:{barber.id}"),
        ],
    ]
    if barber.user and barber.user.role == UserRole.BARBER.value:
        buttons.append([
            InlineKeyboardButton(text="👤 Adminlikni bekor qilish", callback_data=f"owner_revoke_admin:{barber.id}")
        ])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Barberlar ro'yxati", callback_data="owner_back_to_barbers")
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


WEEKDAY_NAMES_UZ = [
    "Dushanba",
    "Seshanba",
    "Chorshanba",
    "Payshanba",
    "Juma",
    "Shanba",
    "Yakshanba",
]


async def render_barber_schedule_view(
    session: AsyncSession, barber: Barber, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    barber_repo = BarberRepository(session)
    wh_list = await barber_repo.get_working_hours(barber.id)
    wh_map = {wh.weekday: wh for wh in wh_list}

    lines = [f"🕒 <b>{barber.display_name}</b> ish vaqti jadvali:\n"]
    buttons = []
    for day_idx, day_name in enumerate(WEEKDAY_NAMES_UZ):
        wh = wh_map.get(day_idx)
        if wh and wh.is_day_off:
            status_text = "Dam olish kuni"
            btn_text = f"🔴 {day_name}: Dam olish"
        elif wh:
            start_str = wh.start_time.strftime("%H:%M")
            end_str = wh.end_time.strftime("%H:%M")
            status_text = f"{start_str} - {end_str}"
            btn_text = f"🟢 {day_name}: {status_text}"
        else:
            status_text = "09:00 - 20:00"
            btn_text = f"🟢 {day_name}: {status_text}"
        lines.append(f"• <b>{day_name}</b>: {status_text}")
        buttons.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"owner_edit_wh:{barber.id}:{day_idx}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Barber ma'lumotlariga qaytish",
            callback_data=f"owner_manage_barber:{barber.id}",
        )
    ])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


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

    day_name = WEEKDAY_NAMES_UZ[weekday]
    if wh and wh.is_day_off:
        status_desc = "Dam olish kuni"
    elif wh:
        status_desc = f"{wh.start_time.strftime('%H:%M')} - {wh.end_time.strftime('%H:%M')}"
    else:
        status_desc = "09:00 - 20:00"

    text = (
        f"🕒 <b>{barber.display_name}</b> — <b>{day_name}</b>\n\n"
        f"Joriy holat: <b>{status_desc}</b>\n\n"
        f"O'zgartirish uchun kerakli tugmani bosing:"
    )
    toggle_text = "🟢 Ish kuni qilish" if (wh and wh.is_day_off) else "🔴 Dam olish kuni qilish"
    buttons = [
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"owner_toggle_dayoff:{barber_id}:{weekday}"),
            InlineKeyboardButton(text="✏️ Vaqtni o'zgartirish", callback_data=f"owner_set_hours_prompt:{barber_id}:{weekday}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Jadvalga qaytish", callback_data=f"owner_barber_schedule:{barber_id}"),
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
    day_name = WEEKDAY_NAMES_UZ[weekday]
    prompt = f"Iltimos, {day_name} uchun ish vaqtini quyidagi formatda kiriting:\nHH:MM-HH:MM (masalan: 09:00-20:00 yoki 10:00-19:00):"
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

    pattern = r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])-([0-1]?[0-9]|2[0-3]):([0-5][0-9])$"
    match = re.match(pattern, text)
    if not match:
        await message.answer(t("owner.err_time_format", lang=lang))
        return

    h1, m1, h2, m2 = map(int, match.groups())
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
    await message.answer(f"✅ Ish vaqti saqlandi!\n\n{text_view}", reply_markup=markup, parse_mode="HTML")


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
        paused_str = " (Dam olishda)" if b.is_paused else ""
        text += f"\n{active_str} #{b.id} {b.display_name}{paused_str}"
        buttons.append([
            InlineKeyboardButton(
                text=f"{active_str} {b.display_name}",
                callback_data=f"owner_manage_barber:{b.id}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text=t("owner.btn_invite_barber", lang=lang),
            callback_data="create_barber_invite",
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
    t("owner.menu_services", "uz"),
    t("owner.menu_services", "uz_cyrl"),
    t("owner.menu_services", "ru"),
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
            InlineKeyboardButton(
                text=f"💈 {b.display_name}",
                callback_data=f"owner_barber_services:{b.id}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=t("common.btn_back_main", lang=lang),
            callback_data="back_to_main_menu",
        )
    ])
    prompt = "✂️ Qaysi barberning xizmatlarini ko'rmoqchisiz?"
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
        rows.append([
            InlineKeyboardButton(
                text=f"{status_icon} {s.name} ({format_money(s.price)}, {s.duration_minutes}m)",
                callback_data=f"toggle_svc:{s.id}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=t("barber.service_add_btn", lang=lang),
            callback_data=f"owner_add_svc:{barber.id}",
        )
    ])
    await call.message.edit_text(
        f"💈 <b>{barber.display_name}</b> xizmatlari:\n(Faol/No-faol qilish uchun ustiga bosing)",
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

    ranking_text = "\n".join(ranking_lines) if ranking_lines else "Hech qanday xizmat ko'rsatilmadi."

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
    t("owner.menu_reports", "uz"),
    t("owner.menu_reports", "uz_cyrl"),
    t("owner.menu_reports", "ru"),
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
        caption=f"📈 {title} hisoboti (CSV)",
    )
    await call.answer()


# -------------------------------------------------------------
# Refunds (Pending Manual Refunds)
# -------------------------------------------------------------
@router.message(F.text.in_([
    t("owner.menu_refunds", "uz"),
    t("owner.menu_refunds", "uz_cyrl"),
    t("owner.menu_refunds", "ru"),
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

    payment_repo = PaymentRepository(session)
    pending_refunds = await payment_repo.get_refund_pending_payments()
    if not pending_refunds:
        await target_msg.answer(t("owner.refunds_empty", lang=lang), reply_markup=get_back_to_main_keyboard(lang))
        return

    await target_msg.answer(t("owner.refunds_title", lang=lang))
    for p in pending_refunds:
        barber_name = p.barber.display_name if p.barber else "Barber"
        nick = p.order.client_display_name if p.order else "Mijoz"
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
    t("owner.menu_block", "uz"),
    t("owner.menu_block", "uz_cyrl"),
    t("owner.menu_block", "ru"),
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
