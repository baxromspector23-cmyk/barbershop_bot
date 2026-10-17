from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.i18n import t
from app.keyboards.common import btn, kbtn, menu_label


def get_owner_main_menu(lang: str = "uz") -> ReplyKeyboardMarkup:
    buttons = [
        [
            kbtn(menu_label("owner.menu_all_queues", lang), icon="stats"),
            kbtn(menu_label("owner.menu_reports", lang), icon="chart"),
        ],
        [
            kbtn(menu_label("owner.menu_info", lang), icon="queue"),
            kbtn(menu_label("owner.menu_barbers", lang), icon="users"),
        ],
        [
            kbtn(menu_label("owner.menu_services", lang), icon="scissors"),
        ],
        [
            kbtn(menu_label("barber.menu_queue", lang), icon="queue"),
            kbtn(menu_label("barber.menu_payments", lang), icon="money"),
        ],
        [
            kbtn(menu_label("barber.menu_pending_receipts", lang), icon="receipt"),
            kbtn(menu_label("barber.menu_walkin", lang), icon="plus"),
        ],
        [
            kbtn(menu_label("barber.menu_toggle_status", lang), icon="refresh"),
        ],
        [
            kbtn(menu_label("owner.menu_refunds", lang), icon="refresh"),
            kbtn(menu_label("owner.menu_block", lang), icon="forbidden"),
        ],
        [
            kbtn(menu_label("barber.menu_lang", lang), icon="lang"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# Alias
get_owner_main_keyboard = get_owner_main_menu


def get_owner_inline_menu(is_paused: bool = False, lang: str = "uz") -> InlineKeyboardMarkup:
    status_btn = (
        btn(text=t("barber.btn_start_work", lang=lang), callback_data="b_menu:toggle_status", icon="play")
        if is_paused
        else btn(text=t("barber.btn_take_break", lang=lang), callback_data="b_menu:toggle_status", icon="pause")
    )
    buttons = [
        [
            btn(text=t("owner.menu_all_queues", lang=lang), callback_data="o_menu:all_queues", icon="stats"),
            btn(text=t("owner.menu_reports", lang=lang), callback_data="o_menu:reports", icon="chart"),
        ],
        [
            btn(text=t("owner.menu_info", lang=lang), callback_data="o_menu:info", icon="queue"),
            btn(text=t("owner.menu_barbers", lang=lang), callback_data="o_menu:barbers", icon="users"),
        ],
        [
            btn(text=t("owner.menu_services", lang=lang), callback_data="o_menu:services", icon="scissors"),
        ],
        [
            btn(text=t("barber.menu_queue", lang=lang), callback_data="b_menu:queue", icon="queue"),
            btn(text=t("barber.menu_payments", lang=lang), callback_data="b_menu:payments", icon="money"),
        ],
        [
            btn(text=t("barber.menu_pending_receipts", lang=lang), callback_data="b_menu:pending_receipts", icon="receipt"),
            btn(text=t("barber.menu_walkin", lang=lang), callback_data="b_menu:walkin", icon="plus"),
        ],
        [
            status_btn,
        ],
        [
            btn(text=t("owner.menu_refunds", lang=lang), callback_data="o_menu:refunds", icon="refresh"),
            btn(text=t("owner.menu_block", lang=lang), callback_data="o_menu:block", icon="forbidden"),
        ],
        [
            btn(text=t("barber.menu_lang", lang=lang), callback_data="b_menu:lang", icon="lang"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_reports_keyboard(period_type: str, offset: int, lang: str = "uz") -> InlineKeyboardMarkup:
    # Top row: period selection
    p_buttons = [
        btn(
            text=f"{'🔘 ' if period_type == 'today' else ''}{t('owner.btn_today', lang=lang)}",
            callback_data="rep:today:0",
            icon="radio" if period_type == "today" else None,
        ),
        btn(
            text=f"{'🔘 ' if period_type == 'week' else ''}{t('owner.btn_week', lang=lang)}",
            callback_data="rep:week:0",
            icon="radio" if period_type == "week" else None,
        ),
        btn(
            text=f"{'🔘 ' if period_type == 'month' else ''}{t('owner.btn_month', lang=lang)}",
            callback_data="rep:month:0",
            icon="radio" if period_type == "month" else None,
        ),
    ]

    # Nav row: prev / next
    nav_buttons = [
        btn(text=t("owner.btn_prev", lang=lang), callback_data=f"rep:{period_type}:{offset - 1}", icon="back"),
        btn(text=t("owner.btn_next", lang=lang), callback_data=f"rep:{period_type}:{offset + 1}", icon="next"),
    ]

    # Action row: download CSV
    action_buttons = [
        btn(
            text=t("owner.btn_csv", lang=lang),
            callback_data=f"rep_csv:{period_type}:{offset}",
            icon="download",
        )
    ]

    back_button = [
        btn(
            text=t("common.btn_back_main", lang=lang),
            callback_data="back_to_main_menu",
            icon="home",
        )
    ]

    return InlineKeyboardMarkup(inline_keyboard=[p_buttons, nav_buttons, action_buttons, back_button])


def get_refund_action_keyboard(payment_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    text=t("owner.btn_refunded", lang=lang),
                    callback_data=f"mark_refunded:{payment_id}",
                    icon="check",
                )
            ]
        ]
    )
