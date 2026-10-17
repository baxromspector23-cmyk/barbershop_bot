from __future__ import annotations

import html
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n import t
from app.keyboards.barber import get_barber_inline_menu, get_barber_main_menu
from app.keyboards.client import get_client_inline_menu, get_client_main_menu
from app.keyboards.common import (
    get_client_phone_registration_keyboard,
    get_language_keyboard,
    get_phone_request_keyboard,
    menu_label,
)
from app.keyboards.owner import get_owner_inline_menu, get_owner_main_menu
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.user_repo import UserRepository
from app.services.queue_service import QueueService
from app.services.user_service import UserService
from app.utils.phone import normalize_uz_phone

logger = logging.getLogger(__name__)
router = Router(name="common_router")


class BarberOnboardingSG(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_photo = State()


class ClientRegistrationSG(StatesGroup):
    waiting_for_phone = State()


def get_role_main_menu(user: User):
    if user.role == UserRole.OWNER.value:
        return get_owner_main_menu(user.language)
    elif user.role == UserRole.BARBER.value:
        return get_barber_main_menu(user.language)
    return get_client_main_menu(user.language)


async def render_role_main_dashboard(
    session: AsyncSession,
    user: User,
) -> tuple[str, InlineKeyboardMarkup]:
    lang = user.language
    if user.role in [UserRole.OWNER.value, UserRole.BARBER.value]:
        barber_repo = BarberRepository(session)
        barber = await barber_repo.get_by_user_id(user.id)
        is_paused = barber.is_paused if barber else False
        display_name = barber.display_name if barber else (user.first_name or "Barber")
        status_str = t("barber.status_paused", lang=lang) if is_paused else t("barber.status_active", lang=lang)

        qs = QueueService(session)
        q_len, _ = await qs.get_barber_queue_metrics(barber.id) if barber else (0, 0)

        if user.role == UserRole.OWNER.value:
            text = t("owner.panel_title", lang=lang, name=display_name, status=status_str, count=q_len)
            markup = get_owner_inline_menu(is_paused=is_paused, lang=lang)
        else:
            text = t("barber.panel_title", lang=lang, name=display_name, status=status_str, count=q_len)
            markup = get_barber_inline_menu(is_paused=is_paused, lang=lang)
    else:
        text = t("client.panel_title", lang=lang)
        markup = get_client_inline_menu(lang=lang)

    return text, markup


@router.message(CommandStart())
async def handle_start(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    lang: str,
    state: FSMContext,
):
    args = command.args
    # Check for barber invite deep link: start=barber_<token>
    if args and args.startswith("barber_"):
        token = args.replace("barber_", "").strip()
        user_service = UserService(session)
        invite = await user_service.validate_barber_invite(token)
        if invite:
            await state.update_data(invite_id=invite.id)
            await state.set_state(BarberOnboardingSG.waiting_for_name)
            welcome_text = t("onboarding.barber_welcome", lang=lang)
            await message.answer(welcome_text, reply_markup=ReplyKeyboardRemove())
            return
        else:
            await message.answer(t("onboarding.invalid_invite", lang=lang))

    # Staff (OWNER and BARBER) go straight to their dashboard
    if user.role in (UserRole.OWNER.value, UserRole.BARBER.value):
        text, markup = await render_role_main_dashboard(session, user)
        await message.answer(text, reply_markup=markup, parse_mode="HTML")
        return

    # If user already registered phone: show profile info and main dashboard
    if user.phone:
        escaped_first = html.escape(user.first_name or "")
        escaped_last = html.escape(user.last_name or "")
        escaped_phone = html.escape(user.phone or "")
        name_line = f"{escaped_first} {escaped_last}".strip()
        profile_text = t(
            "client.profile_text",
            lang=lang,
            first_name=escaped_first,
            name=name_line,
            phone=escaped_phone,
            tg_id=user.telegram_id,
        )
        await message.answer(profile_text, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
        text, markup = await render_role_main_dashboard(session, user)
        await message.answer(text, reply_markup=markup, parse_mode="HTML")
        return

    # /start for a CLIENT without a phone: prompt for phone registration in their language
    await state.set_state(ClientRegistrationSG.waiting_for_phone)
    escaped_first = html.escape(user.first_name or "")
    prompt = t("client.registration_prompt", lang=lang, name=escaped_first)
    await message.answer(
        prompt,
        reply_markup=get_client_phone_registration_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(ClientRegistrationSG.waiting_for_phone, F.contact | F.text)
async def handle_client_registration_phone(
    message: Message,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    lang: str,
):
    phone = None
    sender_id = None
    try:
        if message.from_user:
            sender_id = message.from_user.id
    except (AttributeError, TypeError):
        sender_id = user.telegram_id

    sender_id = sender_id or user.telegram_id

    if message.contact:
        contact_uid = getattr(message.contact, "user_id", None)
        if contact_uid is not None and sender_id is not None and contact_uid != sender_id:
            await message.answer(
                t("common.err_own_contact_required", lang=lang),
                reply_markup=get_client_phone_registration_keyboard(lang),
            )
            return
        phone = normalize_uz_phone(message.contact.phone_number)
    elif message.text:
        phone = normalize_uz_phone(message.text)

    if not phone:
        await message.answer(
            t("common.err_invalid_phone", lang=lang),
            reply_markup=get_client_phone_registration_keyboard(lang),
        )
        return

    user.phone = phone
    user_repo = UserRepository(session)
    await user_repo.update_phone(user.id, phone)
    await session.commit()
    await state.clear()

    escaped_first = html.escape(user.first_name or "")
    escaped_last = html.escape(user.last_name or "")
    escaped_phone = html.escape(user.phone or "")
    name_line = f"{escaped_first} {escaped_last}".strip()
    saved_msg = t(
        "client.registration_success",
        lang=lang,
        name=name_line,
        phone=escaped_phone,
        tg_id=user.telegram_id,
    )
    await message.answer(saved_msg, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
    text, markup = await render_role_main_dashboard(session, user)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


async def remove_reply_markup(message: Message) -> None:
    try:
        rm = await message.answer("🔄", reply_markup=ReplyKeyboardRemove())
        await rm.delete()
    except Exception:
        pass


@router.message(Command("menu"))
async def handle_menu_command(message: Message, session: AsyncSession, user: User):
    await remove_reply_markup(message)
    text, markup = await render_role_main_dashboard(session, user)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("set_lang:"))
async def handle_set_language(
    call: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
):
    new_lang = call.data.split(":")[1]
    repo = UserRepository(session)
    await repo.update_language(user.id, new_lang)
    await session.commit()
    user.language = new_lang

    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass

    if user.role == UserRole.CLIENT.value and not user.phone:
        await state.set_state(ClientRegistrationSG.waiting_for_phone)
        escaped_first = html.escape(user.first_name or "")
        prompt = t("client.registration_prompt", lang=new_lang, name=escaped_first)
        await call.message.answer(
            prompt,
            reply_markup=get_client_phone_registration_keyboard(new_lang),
            parse_mode="HTML",
        )
        return

    text, markup = await render_role_main_dashboard(session, user)
    if call.message:
        await remove_reply_markup(call.message)
    await call.message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data == "back_to_main_menu")
async def handle_back_to_main_menu(call: CallbackQuery, session: AsyncSession, user: User):
    text, markup = await render_role_main_dashboard(session, user)
    try:
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=markup, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.in_(["c_menu:lang", "b_menu:lang", "change_lang"]))
async def handle_change_language_callback(call: CallbackQuery, user: User):
    select_lang_text = t("common.select_lang", lang=user.language)
    try:
        await call.message.edit_text(select_lang_text, reply_markup=get_language_keyboard())
    except Exception:
        await call.message.answer(select_lang_text, reply_markup=get_language_keyboard())
    await call.answer()


@router.message(F.text.in_([
    menu_label("client.menu_lang", "uz"),
    menu_label("client.menu_lang", "uz_cyrl"),
    menu_label("client.menu_lang", "ru"),
    menu_label("barber.menu_lang", "uz"),
    menu_label("barber.menu_lang", "uz_cyrl"),
    menu_label("barber.menu_lang", "ru"),
]))
async def handle_change_language_btn(message: Message, lang: str):
    await remove_reply_markup(message)
    select_lang_text = t("common.select_lang", lang=lang)
    await message.answer(select_lang_text, reply_markup=get_language_keyboard())


# -------------------------------------------------------------
# Barber Onboarding FSM Handlers
# -------------------------------------------------------------
@router.message(BarberOnboardingSG.waiting_for_name)
async def handle_onboarding_name(message: Message, state: FSMContext, lang: str):
    name = (message.text or "").strip()
    if not name:
        await message.answer(t("onboarding.barber_welcome", lang=lang))
        return

    await state.update_data(display_name=name)
    await state.set_state(BarberOnboardingSG.waiting_for_phone)
    prompt = t("onboarding.barber_phone_request", lang=lang)
    await message.answer(prompt, reply_markup=get_phone_request_keyboard(lang))


@router.message(BarberOnboardingSG.waiting_for_phone, F.contact | F.text)
async def handle_onboarding_phone(message: Message, state: FSMContext, lang: str):
    phone = ""
    if message.contact:
        phone = message.contact.phone_number
    elif message.text:
        phone = message.text.strip()

    if not phone or phone == t("common.skip", lang=lang):
        phone = None

    await state.update_data(phone=phone)
    await state.set_state(BarberOnboardingSG.waiting_for_photo)
    prompt = t("onboarding.barber_photo_request", lang=lang)
    await message.answer(prompt, reply_markup=ReplyKeyboardRemove())


@router.message(BarberOnboardingSG.waiting_for_photo, F.photo | F.text)
async def handle_onboarding_photo(
    message: Message,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    lang: str,
):
    photo_file_id = None
    if message.photo:
        photo_file_id = message.photo[-1].file_id

    data = await state.get_data()
    invite_id = data.get("invite_id")
    display_name = data.get("display_name", "Barber")
    phone = data.get("phone", "")

    user_service = UserService(session)
    await user_service.complete_barber_onboarding(
        invite_id=invite_id,
        user=user,
        display_name=display_name,
        phone=phone,
        photo_file_id=photo_file_id,
    )
    await session.commit()
    await state.clear()

    success_text = t("onboarding.barber_activated", lang=lang)
    await message.answer(success_text, reply_markup=ReplyKeyboardRemove())
    text, markup = await render_role_main_dashboard(session, user)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")
