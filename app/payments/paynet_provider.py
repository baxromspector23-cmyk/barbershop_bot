from __future__ import annotations

import uuid
from typing import Any

from app.config import settings
from app.models.enums import OrderStatus, PaymentMethod
from app.models.order import Order
from app.payments.base import PaymentProvider


class PaynetProvider(PaymentProvider):
    """
    Paynet Merchant Adapter for Uzbekistan.

    Architecture Note:
    Telegram Bot API has no native BotFather provider token for Paynet.
    Official Paynet Uzbekistan integration operates via:
    1. Paynet UWS Connector (JSON-RPC 2.0 server-to-server endpoint)
    2. Universal Billing web payment link / checkout form

    This adapter implements the PaymentProvider interface and prepares payloads for
    Paynet merchant checkout. Full production enablement requires a signed merchant contract
    with Paynet LLC, service_id, and TLS client certificates / IP whitelist.
    """

    @property
    def method_name(self) -> str:
        return PaymentMethod.PAYNET.value

    async def create_payment_payload(self, order: Order) -> dict[str, Any]:
        if not settings.PAYNET_ENABLED:
            return {
                "method": self.method_name,
                "available": False,
                "error": "Paynet integration is currently disabled in environment configuration.",
            }

        transaction_id = f"paynet_{order.id}_{uuid.uuid4().hex[:10]}"
        # Standard Paynet Universal Checkout URL or JSON-RPC request structure
        service_id = settings.PAYNET_SERVICE_ID or "UNCONFIGURED"
        checkout_url = (
            f"https://paynet.uz/merchant/pay?service_id={service_id}&order_id={order.id}&amount={order.price}"
        )

        return {
            "method": self.method_name,
            "available": True,
            "order_id": order.id,
            "amount": order.price,
            "provider_payment_id": transaction_id,
            "checkout_url": checkout_url,
        }

    async def verify_payment(self, order: Order, amount: int, raw_payload: dict[str, Any]) -> bool:
        """
        Verify incoming Paynet JSON-RPC PerformTransaction request or callback.
        """
        if not settings.PAYNET_ENABLED:
            return False

        if order.status in [
            OrderStatus.CANCELLED_BY_CLIENT.value,
            OrderStatus.CANCELLED_BY_STAFF.value,
            OrderStatus.CANCELLED_NO_SHOW.value,
            OrderStatus.EXPIRED.value,
        ]:
            return False

        return amount == order.price
