from __future__ import annotations

from typing import Dict

from app.config import settings
from app.models.enums import PaymentMethod
from app.payments.base import PaymentProvider
from app.payments.cash_provider import CashProvider
from app.payments.fake_provider import FakeProvider
from app.payments.paynet_provider import PaynetProvider
from app.payments.telegram_provider import TelegramPaymentProvider


def get_payment_providers() -> dict[str, PaymentProvider]:
    providers: dict[str, PaymentProvider] = {
        PaymentMethod.CASH.value: CashProvider(),
        PaymentMethod.CLICK.value: TelegramPaymentProvider(PaymentMethod.CLICK),
        PaymentMethod.PAYME.value: TelegramPaymentProvider(PaymentMethod.PAYME),
        PaymentMethod.PAYNET.value: PaynetProvider(),
    }
    if settings.PAYMENTS_MODE == "test":
        providers["FAKE"] = FakeProvider()
    return providers
