from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, WebAppInfo

from app.config import settings
from app.i18n import t
from app.keyboards.common import btn, kbtn, menu_label
from app.utils.formatting import format_money

if TYPE_CHECKING:
    from app.models.barber import Barber
    from app.models.service import Service


def _get_webapp_url() -> str:
    base = (settings.SITE_BASE_URL or "https://barbershop-bot-site.onrender.com").strip().rstrip("/")
    return f"{base}/webapp"


def get_client_main_menu(lang: str = "uz") -> ReplyKeyboardMarkup:
    webapp_url = _get_webapp_url()
    buttons = [
        [
            kbtn(menu_label("client.menu_join", lang), icon="barbershop", style="success"),
            kbtn(menu_label("client.menu_my_queue", lang), icon="ticket"),
        ],
        [
            kbtn(menu_label("client.menu_history", lang), icon="history"),
            kbtn(menu_label("client.menu_lang", lang), icon="lang"),
        ],
        [
            kbtn(
                menu_label("client.menu_ai_stylist", lang),
                icon="zap",
                style="primary",
                web_app=WebAppInfo(url=webapp_url),
            ),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# Alias
get_client_main_keyboard = get_client_main_menu


def get_client_inline_menu(lang: str = "uz") -> InlineKeyboardMarkup:
    webapp_url = _get_webapp_url()
    buttons = [
        [
            btn(t("client.menu_join", lang=lang), "c_menu:join", icon="barbershop", style="success"),
            btn(t("client.menu_my_queue", lang=lang), "c_menu:my_queue", icon="ticket"),
        ],
        [
            btn(
                t("client.menu_ai_stylist", lang=lang),
                web_app=WebAppInfo(url=webapp_url),
                icon="zap",
                style="primary",
            ),
        ],
        [
            btn(t("client.menu_history", lang=lang), "c_menu:history", icon="history"),
            btn(t("client.menu_lang", lang=lang), "c_menu:lang", icon="lang"),
        ],
    ]
    if settings.INSTAGRAM_URL:
        buttons.append([
            btn(t("client.btn_instagram", lang=lang), url=settings.INSTAGRAM_URL, icon="instagram")
        ])
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
        btn(
            text=t("client.any_barber", lang=lang),
            callback_data="choose_barber:any",
            style="primary",
            icon="zap",
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

        rows.append([btn(text=label, callback_data=data)])

    rows.append([btn(text=t("common.cancel_btn", lang=lang), callback_data="cancel_action", icon="cross")])
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
            btn(
                text=label,
                callback_data=f"choose_service:{barber_id}:{svc.id}",
            )
        ])
    rows.append([btn(text=t("common.back_btn", lang=lang), callback_data="back_to_barbers", icon="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_payment_timing_keyboard(
    barber_id: int, service_id: int, lang: str = "uz"
) -> InlineKeyboardMarkup:
    enabled = settings.ENABLED_PAYMENT_METHODS
    online = any(m in enabled for m in ("CLICK", "PAYME", "PAYNET")) or (
        "FAKE" in enabled and settings.PAYMENTS_MODE == "test" and settings.ENV != "production"
    )
    if online:
        buttons = [
            [
                btn(
                    text=t("client.pay_now", lang=lang),
                    callback_data=f"pay_timing:now:{barber_id}:{service_id}",
                    icon="card",
                )
            ],
            [
                btn(
                    text=t("client.pay_after", lang=lang),
                    callback_data=f"pay_timing:after:{barber_id}:{service_id}",
                    style="success",
                    icon="timer",
                )
            ],
        ]
    else:
        # Manual payments only (cash / card transfer): the client joins the queue at once and pays later
        buttons = [
            [
                btn(
                    text=t("client.btn_join", lang=lang),
                    callback_data=f"pay_timing:after:{barber_id}:{service_id}",
                    style="success",
                    icon="check",
                )
            ],
        ]
    buttons.append([
        btn(
            text=t("common.cancel_btn", lang=lang),
            callback_data="cancel_action",
            icon="cross",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Aliases
get_pay_timing_keyboard = get_payment_timing_keyboard


def get_payment_methods_keyboard(order_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    buttons = []
    # Manual payment methods: cash (barber confirms) and card transfer (client sends a receipt photo)
    manual_row = []
    if "CASH" in settings.ENABLED_PAYMENT_METHODS:
        manual_row.append(btn(text=t("client.btn_cash", lang=lang), callback_data=f"pay_method:{order_id}:CASH", icon="money"))
    if "TRANSFER" in settings.ENABLED_PAYMENT_METHODS:
        manual_row.append(btn(text=t("client.btn_transfer", lang=lang), callback_data=f"pay_method:{order_id}:TRANSFER", icon="card"))
    if manual_row:
        buttons.append(manual_row)

    main_row = []
    if "CLICK" in settings.ENABLED_PAYMENT_METHODS:
        main_row.append(btn(text="🔹 Click", callback_data=f"pay_method:{order_id}:CLICK", icon="blue_diamond"))
    if "PAYME" in settings.ENABLED_PAYMENT_METHODS:
        main_row.append(btn(text="🔸 Payme", callback_data=f"pay_method:{order_id}:PAYME", icon="orange_diamond"))
    if main_row:
        buttons.append(main_row)

    if settings.PAYNET_ENABLED and "PAYNET" in settings.ENABLED_PAYMENT_METHODS:
        buttons.append([btn(text="🟢 Paynet", callback_data=f"pay_method:{order_id}:PAYNET", icon="green")])

    if (
        settings.PAYMENTS_MODE == "test"
        and settings.ENV != "production"
        and "FAKE" in settings.ENABLED_PAYMENT_METHODS
    ):
        buttons.append([btn(text="🧪 Test (FAKE)", callback_data=f"pay_method:{order_id}:FAKE")])

    buttons.append([btn(text=t("common.cancel_btn", lang=lang), callback_data="cancel_action", icon="cross")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_my_queue_keyboard(order_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    buttons = [
        [
            btn(
                text=t("client.btn_pay", lang=lang),
                callback_data=f"pay_open:{order_id}",
                style="primary",
                icon="card",
            )
        ],
        [
            btn(
                text=t("client.refresh_btn", lang=lang),
                callback_data=f"refresh_queue:{order_id}",
                icon="refresh",
            )
        ],
        [
            btn(
                text=t("client.cancel_queue_btn", lang=lang),
                callback_data=f"cancel_queue_prompt:{order_id}",
                style="danger",
                icon="cross",
            )
        ],
        [
            btn(
                text=t("common.btn_back_main", lang=lang),
                callback_data="back_to_main_menu",
                icon="home",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Alias
get_order_paid_menu = get_my_queue_keyboard


def get_cancel_confirm_keyboard(order_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    buttons = [
        [
            btn(
                text=t("common.confirm_btn", lang=lang),
                callback_data=f"confirm_cancel_queue:{order_id}",
                icon="check",
            ),
            btn(
                text=t("common.back_btn", lang=lang),
                callback_data=f"refresh_queue:{order_id}",
                icon="back",
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_receipt_prompt_keyboard(order_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(text=t("payments.btn_send_receipt", lang=lang), callback_data=f"tr_send:{order_id}", style="primary", icon="attach")],
        [btn(text=t("common.btn_back_main", lang=lang), callback_data="back_to_main_menu", icon="home")],
    ])


# Alias
get_pending_receipt_keyboard = get_receipt_prompt_keyboard


def get_receipt_cancel_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(text=t("common.cancel_btn", lang=lang), callback_data="tr_cancel", icon="cross")],
    ])


def get_ai_stylist_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    webapp_url = _get_webapp_url()
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            btn(
                text=t("client.menu_ai_stylist", lang=lang),
                web_app=WebAppInfo(url=webapp_url),
                icon="zap",
                style="primary",
            )
        ],
        [btn(text=t("common.btn_back_main", lang=lang), callback_data="back_to_main_menu", icon="home")],
    ])

