from __future__ import annotations

from typing import Any

from app.config import settings
from app.models.enums import OrderStatus, PaymentMethod
from app.models.order import Order
from app.payments.base import PaymentProvider


class TelegramPaymentProvider(PaymentProvider):
    def __init__(self, method: PaymentMethod):
        self._method = method

    @property
    def method_name(self) -> str:
        return self._method.value

    def get_provider_token(self) -> str:
        if self._method == PaymentMethod.PAYME:
            return settings.PAYME_PROVIDER_TOKEN or ""
        elif self._method == PaymentMethod.CLICK:
            return settings.CLICK_PROVIDER_TOKEN or ""
        return ""

    async def create_payment_payload(self, order: Order) -> dict[str, Any]:
        """
        Build Telegram invoice parameters.
        Currency: UZS.
        Telegram requires smallest currency units (tiyin: amount * 100).
        """
        amount_tiyin = order.price * 100
        return {
            "method": self.method_name,
            "title": f"Barbershop: {order.service_name}",
            "description": f"Buyurtma #{order.ticket_no} ({order.service_name}) uchun to'lov",
            "payload": f"order_{order.id}_{self.method_name}",
            "provider_token": self.get_provider_token(),
            "currency": "UZS",
            "prices": [{"label": order.service_name, "amount": amount_tiyin}],
            "order_id": order.id,
            "amount_uzs": order.price,
            "amount_tiyin": amount_tiyin,
        }

    async def verify_payment(self, order: Order, amount: int, raw_payload: dict[str, Any]) -> bool:
        """
        Verifies pre-checkout query.
        Amount must match order price (checked in tiyin or so'm).
        Order must not be in cancelled or expired state.
        """
        if order.status in [
            OrderStatus.CANCELLED_BY_CLIENT.value,
            OrderStatus.CANCELLED_BY_STAFF.value,
            OrderStatus.CANCELLED_NO_SHOW.value,
            OrderStatus.EXPIRED.value,
        ]:
            return False

        # In Telegram payments, total_amount in PreCheckoutQuery is in tiyin (amount * 100)
        expected_tiyin = order.price * 100
        if amount == expected_tiyin or amount == order.price:
            return True
        return False
