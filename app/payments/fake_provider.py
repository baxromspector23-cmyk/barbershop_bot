from __future__ import annotations

import uuid
from typing import Any

from app.config import settings
from app.models.order import Order
from app.payments.base import PaymentProvider


class FakeProvider(PaymentProvider):
    """
    Test provider used when PAYMENTS_MODE == 'test'.
    Simulates instantaneous payment confirmations without real credentials.
    Must never be enabled in production.
    """

    @property
    def method_name(self) -> str:
        return "FAKE"

    async def create_payment_payload(self, order: Order) -> dict[str, Any]:
        if settings.ENV == "production" or settings.PAYMENTS_MODE != "test":
            raise RuntimeError("FakeProvider is prohibited in production!")

        fake_tx_id = f"fake_{uuid.uuid4().hex[:12]}"
        return {
            "method": self.method_name,
            "order_id": order.id,
            "amount": order.price,
            "provider_payment_id": fake_tx_id,
            "test_confirmation_url": f"/internal/test-pay?order_id={order.id}&tx_id={fake_tx_id}",
        }

    async def verify_payment(self, order: Order, amount: int, raw_payload: dict[str, Any]) -> bool:
        if settings.ENV == "production" or settings.PAYMENTS_MODE != "test":
            return False
        return amount == order.price
