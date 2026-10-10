from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.models.order import Order


class PaymentProvider(ABC):
    @property
    @abstractmethod
    def method_name(self) -> str:
        """Name of payment method (e.g. PAYME, CLICK, PAYNET, CASH, FAKE)."""

    @abstractmethod
    async def create_payment_payload(self, order: Order) -> dict[str, Any]:
        """Generate invoice payload or payment URL for client."""

    @abstractmethod
    async def verify_payment(self, order: Order, amount: int, raw_payload: dict[str, Any]) -> bool:
        """Verify pre-checkout query or incoming callback validity."""
