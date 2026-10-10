from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.i18n import t
from app.models.barber import Barber
from app.models.service import Service
from app.utils.formatting import format_money


def get_client_main_menu(lang: str = "uz") -> ReplyKeyboardMarkup:
    buttons = [
        [
            KeyboardButton(text=t("client.menu_join", lang=lang)),
            KeyboardButton(text=t("client.menu_my_queue", lang=lang)),
        ],
        [
            KeyboardButton(text=t("client.menu_history", lang=lang)),
            KeyboardButton(text=t("client.menu_lang", lang=lang)),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_client_inline_menu(lang: str = "uz") -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=t("client.menu_join", lang=lang), callback_data="c_menu:join"),
            InlineKeyboardButton(text=t("client.menu_my_queue", lang=lang), callback_data="c_menu:my_queue"),
        ],
        [
            InlineKeyboardButton(text=t("client.menu_history", lang=lang), callback_data="c_menu:history"),
            InlineKeyboardButton(text=t("client.menu_lang", lang=lang), callback_data="c_menu:lang"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_barbers_keyboard(
    barbers_with_metrics: list[tuple[Barber, int, int, bool]], lang: str = "uz"
) -> InlineKeyboardMarkup:
    """
    List active barbers.
    Each item: (barber, queue_len, wait_min, is_available)
    """
    rows = []
    # Any free barber option
    rows.append([
        InlineKeyboardButton(
            text=t("client.any_barber", lang=lang),
            callback_data="choose_barber:any",
        )
    ])

    for barber, q_len, wait_min, is_avail in barbers_with_metrics:
        if is_avail:
            label = t(
                "client.barber_item",
                lang=lang,
                name=barber.display_name,
                queue_len=q_len,
                wait_min=wait_min,
            )
            data = f"choose_barber:{barber.id}"
        else:
            label = t(
                "client.barber_unavailable",
                lang=lang,
                name=barber.display_name,
            )
            data = "noop:closed"

        rows.append([InlineKeyboardButton(text=label, callback_data=data)])

    rows.append([InlineKeyboardButton(text=t("common.cancel_btn", lang=lang), callback_data="cancel_action")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_services_keyboard(
    services: list[Service], barber_id: int, lang: str = "uz"
) -> InlineKeyboardMarkup:
    rows = []
    for svc in services:
        price_fmt = format_money(svc.price)
        label = t(
            "client.service_item",
            lang=lang,
            name=svc.name,
            price=price_fmt,
            duration=svc.duration_minutes,
        )
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"choose_service:{barber_id}:{svc.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text=t("common.back_btn", lang=lang), callback_data="back_to_barbers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_payment_timing_keyboard(
    barber_id: int, service_id: int, lang: str = "uz"
) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=t("client.pay_now", lang=lang),
                callback_data=f"pay_timing:now:{barber_id}:{service_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=t("client.pay_after", lang=lang),
                callback_data=f"pay_timing:after:{barber_id}:{service_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=t("common.cancel_btn", lang=lang),
                callback_data="cancel_action",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_payment_methods_keyboard(order_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    from app.config import settings

    buttons = []
    main_row = []
    if "CLICK" in settings.ENABLED_PAYMENT_METHODS:
        main_row.append(InlineKeyboardButton(text="🔹 Click", callback_data=f"pay_method:{order_id}:CLICK"))
    if "PAYME" in settings.ENABLED_PAYMENT_METHODS:
        main_row.append(InlineKeyboardButton(text="🔸 Payme", callback_data=f"pay_method:{order_id}:PAYME"))
    if main_row:
        buttons.append(main_row)

    if settings.PAYNET_ENABLED and "PAYNET" in settings.ENABLED_PAYMENT_METHODS:
        buttons.append([InlineKeyboardButton(text="🟢 Paynet", callback_data=f"pay_method:{order_id}:PAYNET")])

    if (
        settings.PAYMENTS_MODE == "test"
        and settings.ENV != "production"
        and "FAKE" in settings.ENABLED_PAYMENT_METHODS
    ):
        buttons.append([InlineKeyboardButton(text="🧪 Test (FAKE)", callback_data=f"pay_method:{order_id}:FAKE")])

    buttons.append([InlineKeyboardButton(text=t("common.cancel_btn", lang=lang), callback_data="cancel_action")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_my_queue_keyboard(order_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=t("client.refresh_btn", lang=lang),
                callback_data=f"refresh_queue:{order_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=t("client.cancel_queue_btn", lang=lang),
                callback_data=f"cancel_queue_prompt:{order_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text=t("common.btn_back_main", lang=lang),
                callback_data="back_to_main_menu",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_confirm_keyboard(order_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=t("common.confirm_btn", lang=lang),
                callback_data=f"confirm_cancel_queue:{order_id}",
            ),
            InlineKeyboardButton(
                text=t("common.back_btn", lang=lang),
                callback_data=f"refresh_queue:{order_id}",
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
