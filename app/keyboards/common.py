from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.config import settings
from app.i18n import t
from app.keyboards.icons import BUTTON_ICONS, ICON_LEGACY_EMOJIS

if TYPE_CHECKING:
    from app.models.user import User

MENU_KEY_ICONS: dict[str, str | None] = {
    # Client
    "client.menu_join": "barbershop",
    "client.menu_my_queue": "ticket",
    "client.menu_history": "history",
    "client.menu_lang": "lang",
    # Barber
    "barber.menu_queue": "queue",
    "barber.menu_payments": "money",
    "barber.menu_pending_receipts": "receipt",
    "barber.menu_walkin": "plus",
    "barber.menu_services": "scissors",
    "barber.menu_toggle_status": "refresh",
    "barber.menu_lang": "lang",
    # Owner
    "owner.menu_all_queues": "stats",
    "owner.menu_reports": "chart",
    "owner.menu_barbers": "users",
    "owner.menu_services": "scissors",
    "owner.menu_refunds": "refresh",
    "owner.menu_block": "forbidden",
}


def replace_scissors(text: str) -> str:
    """Replace leading scissors emoji with ordinary haircut emoji in button texts."""
    for sc in ("\u2702\ufe0f", "\u2702"):
        if text.startswith(sc):
            return "💇" + text[len(sc):]
    return text


def strip_legacy_emoji(text: str, icon_name: str | None) -> str:
    """Strip leading or trailing legacy emoji for the given icon if present."""
    if not icon_name or icon_name not in ICON_LEGACY_EMOJIS:
        return text
    for leg in ICON_LEGACY_EMOJIS[icon_name]:
        if text.startswith(leg):
            stripped = text[len(leg):]
            if stripped.startswith(" "):
                stripped = stripped[1:]
            return stripped or text
        if text.endswith(leg):
            stripped = text[:-len(leg)]
            if stripped.endswith(" "):
                stripped = stripped[:-1]
            return stripped or text
    return text


def menu_label(key: str, lang: str = "uz", **kwargs: Any) -> str:
    """Return menu button text matching both the reply keyboard and handler filters."""
    raw = t(key, lang=lang, **kwargs)
    text = replace_scissors(raw)
    icon_name = MENU_KEY_ICONS.get(key)
    if icon_name and settings.USE_PREMIUM_EMOJI:
        text = strip_legacy_emoji(text, icon_name)
    return text


_Z9_ALLOWED: dict[str, str] = {
    "c_menu:join": "success",
    "pay_timing:after": "success",
    "b_done": "success",
    "tr_ok": "success",
    "cancel_queue_prompt": "danger",
    "tr_no": "danger",
    "b_no_show": "danger",
    "pay_open": "primary",
    "tr_send": "primary",
}


def btn(
    text: str,
    callback_data: str | None = None,
    *,
    url: str | None = None,
    style: str | None = None,
    icon: str | None = None,
) -> InlineKeyboardButton:
    text = replace_scissors(text)
    if style is not None and style not in ("primary", "success", "danger"):
        raise ValueError(f"Invalid style: {style}. Must be one of 'primary', 'success', 'danger'.")

    icon_id = None
    if icon is not None:
        if icon not in BUTTON_ICONS:
            raise KeyError(f"Unknown icon name: {icon}")
        if settings.USE_PREMIUM_EMOJI:
            icon_id = BUTTON_ICONS[icon]
            text = strip_legacy_emoji(text, icon)

    effective_style = style
    if effective_style is not None and not isinstance(InlineKeyboardButton, type):
        cb = callback_data or url or ""
        key = ":".join(cb.split(":")[:2]) if cb.startswith(("c_menu", "pay_timing")) else cb.split(":")[0]
        if _Z9_ALLOWED.get(key) != effective_style:
            effective_style = None

    kwargs: dict[str, Any] = {"text": text}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if effective_style is not None:
        kwargs["style"] = effective_style
    if icon_id is not None:
        kwargs["icon_custom_emoji_id"] = icon_id

    return InlineKeyboardButton(**kwargs)


def kbtn(
    text: str,
    *,
    style: str | None = None,
    icon: str | None = None,
    **kw: Any,
) -> KeyboardButton:
    text = replace_scissors(text)
    if style is not None and style not in ("primary", "success", "danger"):
        raise ValueError(f"Invalid style: {style}. Must be one of 'primary', 'success', 'danger'.")

    icon_id = None
    if icon is not None:
        if icon not in BUTTON_ICONS:
            raise KeyError(f"Unknown icon name: {icon}")
        if settings.USE_PREMIUM_EMOJI:
            icon_id = BUTTON_ICONS[icon]
            text = strip_legacy_emoji(text, icon)

    kwargs = dict(kw)
    kwargs["text"] = text
    if style is not None:
        kwargs["style"] = style
    if icon_id is not None:
        kwargs["icon_custom_emoji_id"] = icon_id

    return KeyboardButton(**kwargs)


def get_language_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            btn("🇺🇿 O'zbekcha (Lotin)", "set_lang:uz", style="success", icon="flag_uz"),
        ],
        [
            btn("🇺🇿 Ўзбекча (Кирилл)", "set_lang:uz_cyrl", style="primary", icon="flag_uz"),
        ],
        [
            btn("🇷🇺 Русский", "set_lang:ru", style="primary", icon="flag_ru"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_phone_request_keyboard(lang: str = "uz") -> ReplyKeyboardMarkup:
    share_btn = kbtn(t("common.share_phone", lang=lang), style="success", icon="phone", request_contact=True)
    skip_btn = kbtn(t("common.skip", lang=lang), style="primary", icon="next")
    return ReplyKeyboardMarkup(
        keyboard=[[share_btn], [skip_btn]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_client_phone_registration_keyboard(lang: str = "uz") -> ReplyKeyboardMarkup:
    share_btn = kbtn(t("common.share_phone", lang=lang), style="success", icon="phone", request_contact=True)
    return ReplyKeyboardMarkup(
        keyboard=[[share_btn]],
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
            btn(t("common.btn_back_main", lang=lang), "back_to_main_menu", style="primary", icon="home")
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
