from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.i18n import t

if TYPE_CHECKING:
    from app.models.user import User


def get_language_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🇺🇿 O'zbekcha (Lotin)", callback_data="set_lang:uz"),
        ],
        [
            InlineKeyboardButton(text="🇺🇿 Ўзбекча (Кирилл)", callback_data="set_lang:uz_cyrl"),
        ],
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang:ru"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_phone_request_keyboard(lang: str = "uz") -> ReplyKeyboardMarkup:
    share_btn = KeyboardButton(text=t("common.share_phone", lang=lang), request_contact=True)
    skip_btn = KeyboardButton(text=t("common.skip", lang=lang))
    return ReplyKeyboardMarkup(
        keyboard=[[share_btn], [skip_btn]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_role_main_menu(user: User) -> ReplyKeyboardMarkup:
    from app.keyboards.barber import get_barber_main_menu
    from app.keyboards.client import get_client_main_menu
    from app.keyboards.owner import get_owner_main_menu
    from app.models.enums import UserRole

    if user.role == UserRole.OWNER.value:
        return get_owner_main_menu(user.language)
    elif user.role == UserRole.BARBER.value:
        return get_barber_main_menu(user.language)
    return get_client_main_menu(user.language)


def get_back_to_main_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=t("common.btn_back_main", lang=lang), callback_data="back_to_main_menu")
        ]]
    )


def get_role_inline_menu(user: User, is_paused: bool = False) -> InlineKeyboardMarkup:
    from app.keyboards.barber import get_barber_inline_menu
    from app.keyboards.client import get_client_inline_menu
    from app.keyboards.owner import get_owner_inline_menu
    from app.models.enums import UserRole

    if user.role == UserRole.OWNER.value:
        return get_owner_inline_menu(is_paused=is_paused, lang=user.language)
    elif user.role == UserRole.BARBER.value:
        return get_barber_inline_menu(is_paused=is_paused, lang=user.language)
    return get_client_inline_menu(user.language)
