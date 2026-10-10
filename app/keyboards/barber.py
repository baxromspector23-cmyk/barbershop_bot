from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.i18n import t
from app.models.enums import OrderStatus
from app.models.order import Order


def get_barber_main_menu(lang: str = "uz") -> ReplyKeyboardMarkup:
    buttons = [
        [
            KeyboardButton(text=t("barber.menu_queue", lang=lang)),
            KeyboardButton(text=t("barber.menu_payments", lang=lang)),
        ],
        [
            KeyboardButton(text=t("barber.menu_walkin", lang=lang)),
            KeyboardButton(text=t("barber.menu_toggle_status", lang=lang)),
        ],
        [
            KeyboardButton(text=t("barber.menu_services", lang=lang)),
            KeyboardButton(text=t("barber.menu_lang", lang=lang)),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_barber_inline_menu(is_paused: bool = False, lang: str = "uz") -> InlineKeyboardMarkup:
    status_btn = (
        InlineKeyboardButton(text=t("barber.btn_start_work", lang=lang), callback_data="b_menu:toggle_status")
        if is_paused
        else InlineKeyboardButton(text=t("barber.btn_take_break", lang=lang), callback_data="b_menu:toggle_status")
    )
    buttons = [
        [
            InlineKeyboardButton(text=t("barber.menu_queue", lang=lang), callback_data="b_menu:queue"),
            InlineKeyboardButton(text=t("barber.menu_payments", lang=lang), callback_data="b_menu:payments"),
        ],
        [
            InlineKeyboardButton(text=t("barber.menu_walkin", lang=lang), callback_data="b_menu:walkin"),
            InlineKeyboardButton(text=t("barber.menu_services", lang=lang), callback_data="b_menu:services"),
        ],
        [
            status_btn,
        ],
        [
            InlineKeyboardButton(text=t("barber.menu_lang", lang=lang), callback_data="b_menu:lang"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_barber_order_actions(order: Order, lang: str = "uz") -> InlineKeyboardMarkup:
    rows = []
    if order.status == OrderStatus.CALLED.value:
        rows.append([
            InlineKeyboardButton(text=t("barber.btn_arrived", lang=lang), callback_data=f"b_arrived:{order.id}"),
            InlineKeyboardButton(text=t("barber.btn_no_show", lang=lang), callback_data=f"b_no_show:{order.id}"),
        ])
        rows.append([
            InlineKeyboardButton(text=t("barber.btn_cancel", lang=lang), callback_data=f"b_cancel:{order.id}"),
        ])
    elif order.status == OrderStatus.IN_SERVICE.value:
        rows.append([
            InlineKeyboardButton(text=t("barber.btn_done", lang=lang), callback_data=f"b_done:{order.id}"),
            InlineKeyboardButton(text=t("barber.btn_cash", lang=lang), callback_data=f"b_cash:{order.id}"),
        ])
    elif order.status == OrderStatus.WAITING.value:
        rows.append([
            InlineKeyboardButton(text=t("barber.btn_cancel", lang=lang), callback_data=f"b_cancel:{order.id}"),
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)
