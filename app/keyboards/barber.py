from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.i18n import t
from app.keyboards.common import btn, kbtn, menu_label
from app.models.enums import OrderStatus

if TYPE_CHECKING:
    from app.models.order import Order


def get_barber_main_menu(lang: str = "uz") -> ReplyKeyboardMarkup:
    buttons = [
        [
            kbtn(menu_label("barber.menu_queue", lang), icon="queue", style="primary"),
            kbtn(menu_label("barber.menu_payments", lang), icon="money", style="success"),
        ],
        [
            kbtn(menu_label("barber.menu_pending_receipts", lang), icon="receipt", style="primary"),
            kbtn(menu_label("barber.menu_walkin", lang), icon="plus", style="success"),
        ],
        [
            kbtn(menu_label("barber.menu_services", lang), icon="scissors", style="primary"),
            kbtn(menu_label("barber.menu_toggle_status", lang), icon="refresh", style="primary"),
        ],
        [
            kbtn(menu_label("barber.menu_lang", lang), icon="lang", style="primary"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# Alias
get_barber_main_keyboard = get_barber_main_menu


def get_barber_inline_menu(is_paused: bool = False, lang: str = "uz") -> InlineKeyboardMarkup:
    status_btn = (
        btn(text=t("barber.btn_start_work", lang=lang), callback_data="b_menu:toggle_status", style="success", icon="play")
        if is_paused
        else btn(text=t("barber.btn_take_break", lang=lang), callback_data="b_menu:toggle_status", style="danger", icon="pause")
    )
    buttons = [
        [
            btn(text=t("barber.menu_queue", lang=lang), callback_data="b_menu:queue", style="primary", icon="queue"),
            btn(text=t("barber.menu_payments", lang=lang), callback_data="b_menu:payments", style="success", icon="money"),
        ],
        [
            btn(text=t("barber.menu_pending_receipts", lang=lang), callback_data="b_menu:pending_receipts", style="primary", icon="receipt"),
            btn(text=t("barber.menu_walkin", lang=lang), callback_data="b_menu:walkin", style="success", icon="plus"),
        ],
        [
            btn(text=t("barber.menu_services", lang=lang), callback_data="b_menu:services", style="primary", icon="scissors"),
            status_btn,
        ],
        [
            btn(text=t("barber.menu_lang", lang=lang), callback_data="b_menu:lang", style="primary", icon="lang"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_barber_order_actions(order: Order, lang: str = "uz") -> InlineKeyboardMarkup:
    rows = []
    if order.status == OrderStatus.CALLED.value:
        rows.append([
            btn(text=t("barber.btn_arrived", lang=lang), callback_data=f"b_arrived:{order.id}", style="success", icon="check"),
            btn(text=t("barber.btn_no_show", lang=lang), callback_data=f"b_no_show:{order.id}", style="danger", icon="cross"),
        ])
        rows.append([
            btn(text=t("barber.btn_cancel", lang=lang), callback_data=f"b_cancel:{order.id}", style="danger", icon="forbidden"),
        ])
    elif order.status in (OrderStatus.IN_SERVICE.value, "IN_PROGRESS"):
        rows.append([
            btn(text=t("barber.btn_done", lang=lang), callback_data=f"b_done:{order.id}", style="success", icon="scissors"),
            btn(text=t("barber.btn_cash", lang=lang), callback_data=f"b_cash:{order.id}", style="primary", icon="money"),
        ])
    elif order.status == OrderStatus.WAITING.value:
        rows.append([
            btn(text=t("barber.btn_cancel", lang=lang), callback_data=f"b_cancel:{order.id}", style="danger", icon="forbidden"),
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# Alias
get_order_action_keyboard = get_barber_order_actions


