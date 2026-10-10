from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.i18n import t


def get_owner_main_menu(lang: str = "uz") -> ReplyKeyboardMarkup:
    buttons = [
        [
            KeyboardButton(text=t("owner.menu_all_queues", lang=lang)),
            KeyboardButton(text=t("owner.menu_reports", lang=lang)),
        ],
        [
            KeyboardButton(text=t("owner.menu_barbers", lang=lang)),
            KeyboardButton(text=t("owner.menu_services", lang=lang)),
        ],
        [
            KeyboardButton(text=t("barber.menu_queue", lang=lang)),
            KeyboardButton(text=t("barber.menu_payments", lang=lang)),
        ],
        [
            KeyboardButton(text=t("barber.menu_walkin", lang=lang)),
            KeyboardButton(text=t("barber.menu_toggle_status", lang=lang)),
        ],
        [
            KeyboardButton(text=t("owner.menu_refunds", lang=lang)),
            KeyboardButton(text=t("owner.menu_block", lang=lang)),
        ],
        [
            KeyboardButton(text=t("barber.menu_lang", lang=lang)),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_owner_inline_menu(is_paused: bool = False, lang: str = "uz") -> InlineKeyboardMarkup:
    status_btn = (
        InlineKeyboardButton(text=t("barber.btn_start_work", lang=lang), callback_data="b_menu:toggle_status")
        if is_paused
        else InlineKeyboardButton(text=t("barber.btn_take_break", lang=lang), callback_data="b_menu:toggle_status")
    )
    buttons = [
        [
            InlineKeyboardButton(text=t("owner.menu_all_queues", lang=lang), callback_data="o_menu:all_queues"),
            InlineKeyboardButton(text=t("owner.menu_reports", lang=lang), callback_data="o_menu:reports"),
        ],
        [
            InlineKeyboardButton(text=t("owner.menu_barbers", lang=lang), callback_data="o_menu:barbers"),
            InlineKeyboardButton(text=t("owner.menu_services", lang=lang), callback_data="o_menu:services"),
        ],
        [
            InlineKeyboardButton(text=t("barber.menu_queue", lang=lang), callback_data="b_menu:queue"),
            InlineKeyboardButton(text=t("barber.menu_payments", lang=lang), callback_data="b_menu:payments"),
        ],
        [
            InlineKeyboardButton(text=t("barber.menu_walkin", lang=lang), callback_data="b_menu:walkin"),
            status_btn,
        ],
        [
            InlineKeyboardButton(text=t("owner.menu_refunds", lang=lang), callback_data="o_menu:refunds"),
            InlineKeyboardButton(text=t("owner.menu_block", lang=lang), callback_data="o_menu:block"),
        ],
        [
            InlineKeyboardButton(text=t("barber.menu_lang", lang=lang), callback_data="b_menu:lang"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_reports_keyboard(period_type: str, offset: int, lang: str = "uz") -> InlineKeyboardMarkup:
    # Top row: period selection
    p_buttons = [
        InlineKeyboardButton(
            text=f"{'🔘 ' if period_type == 'today' else ''}{t('owner.btn_today', lang=lang)}",
            callback_data="rep:today:0",
        ),
        InlineKeyboardButton(
            text=f"{'🔘 ' if period_type == 'week' else ''}{t('owner.btn_week', lang=lang)}",
            callback_data="rep:week:0",
        ),
        InlineKeyboardButton(
            text=f"{'🔘 ' if period_type == 'month' else ''}{t('owner.btn_month', lang=lang)}",
            callback_data="rep:month:0",
        ),
    ]

    # Nav row: prev / next
    nav_buttons = [
        InlineKeyboardButton(text=t("owner.btn_prev", lang=lang), callback_data=f"rep:{period_type}:{offset - 1}"),
        InlineKeyboardButton(text=t("owner.btn_next", lang=lang), callback_data=f"rep:{period_type}:{offset + 1}"),
    ]

    # Action row: download CSV
    action_buttons = [
        InlineKeyboardButton(
            text=t("owner.btn_csv", lang=lang),
            callback_data=f"rep_csv:{period_type}:{offset}",
        )
    ]

    back_button = [
        InlineKeyboardButton(
            text=t("common.btn_back_main", lang=lang),
            callback_data="back_to_main_menu",
        )
    ]

    return InlineKeyboardMarkup(inline_keyboard=[p_buttons, nav_buttons, action_buttons, back_button])


def get_refund_action_keyboard(payment_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("owner.btn_refunded", lang=lang),
                    callback_data=f"mark_refunded:{payment_id}",
                )
            ]
        ]
    )
