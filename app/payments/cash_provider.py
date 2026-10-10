from __future__ import annotations

import uuid
from typing import Any

from app.models.enums import PaymentMethod
from app.models.order import Order
from app.payments.base import PaymentProvider


class CashProvider(PaymentProvider):
    @property
    def method_name(self) -> str:
        return PaymentMethod.CASH.value

    async def create_payment_payload(self, order: Order) -> dict[str, Any]:
        return {
            "method": self.method_name,
            "order_id": order.id,
            "amount": order.price,
            "provider_payment_id": f"cash_{order.id}_{uuid.uuid4().hex[:8]}",
        }

    async def verify_payment(self, order: Order, amount: int, raw_payload: dict[str, Any]) -> bool:
        # Cash is confirmed by the barber directly in the shop
        return amount == order.price
