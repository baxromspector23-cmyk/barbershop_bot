from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.i18n import t
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.models.payment import Payment
from app.payments import get_payment_providers
from app.repositories.audit_repo import AuditRepository
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.notification_service import NotificationService
from app.services.queue_service import QueueService
from app.utils.formatting import format_money
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


class PaymentException(Exception):
    pass


class DuplicatePaymentError(PaymentException):
    pass


class AmountMismatchError(PaymentException):
    pass


class PaymentService:
    def __init__(
        self,
        session: AsyncSession,
        notifier: NotificationService | None = None,
    ):
        self.session = session
        self.notifier = notifier or NotificationService()
        self.payment_repo = PaymentRepository(session)
        self.order_repo = OrderRepository(session)
        self.barber_repo = BarberRepository(session)
        self.audit_repo = AuditRepository(session)
        self.providers = get_payment_providers()

    async def get_or_create_pending_payment(
        self, order_id: int, method: str
    ) -> tuple[Payment, dict[str, Any]]:
        """Get or initiate a payment for an order with a chosen method."""
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise PaymentException(f"Order #{order_id} not found")

        provider = self.providers.get(method.upper())
        if not provider:
            raise PaymentException(f"Payment method '{method}' is not supported")

        payload = await provider.create_payment_payload(order)
        provider_payment_id = payload.get("provider_payment_id") or f"{method}_{order.id}"

        # Check existing payment
        existing = await self.payment_repo.get_by_order_id(order.id)
        if existing and existing.status == PaymentStatus.PENDING.value:
            existing.method = method.upper()
            existing.provider_payment_id = provider_payment_id
            await self.session.flush()
            return existing, payload

        payment = await self.payment_repo.create_payment(
            order_id=order.id,
            barber_id=order.barber_id,
            client_id=order.client_id,
            amount=order.price,
            method=method.upper(),
            provider_payment_id=provider_payment_id,
            status=PaymentStatus.PENDING.value,
            raw_payload=payload,
        )
        await self.session.flush()
        return payment, payload

    async def handle_successful_payment(
        self,
        method: str,
        provider_payment_id: str,
        amount: int,
        order_id: int,
        raw_payload: dict[str, Any] | None = None,
    ) -> Payment:
        """
        Idempotent payment confirmation handler:
        - Checks uniqueness on (method, provider_payment_id)
        - Verifies amount against order price
        - Marks payment as PAID
        - If order was PENDING_PAYMENT, activates order into queue
        - Notifies barber with client nick, amount, method
        - Notifies client with receipt
        """
        existing = await self.payment_repo.get_by_provider_id(method, provider_payment_id)
        if existing:
            logger.info("Payment %s:%s already exists (status=%s). Idempotent return.", method, provider_payment_id, existing.status)
            return existing

        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise PaymentException(f"Order #{order_id} not found")

        # Amount verification (in so'm, or in tiyin for Telegram)
        if amount != order.price and amount != (order.price * 100):
            raise AmountMismatchError(f"Amount {amount} does not match order price {order.price}")

        payment_amount_uzs = order.price
        current_time = now_utc()

        # Check if order is already dead (cancelled or expired)
        if order.status in [
            OrderStatus.CANCELLED_BY_CLIENT.value,
            OrderStatus.CANCELLED_BY_STAFF.value,
            OrderStatus.CANCELLED_NO_SHOW.value,
            OrderStatus.EXPIRED.value,
        ]:
            payment = await self.payment_repo.create_payment(
                order_id=order.id,
                barber_id=order.barber_id,
                client_id=order.client_id,
                amount=payment_amount_uzs,
                method=method,
                provider_payment_id=provider_payment_id,
                status=PaymentStatus.REFUND_PENDING.value,
                raw_payload=raw_payload,
            )
            payment.refund_reason = "DEAD_ORDER"
            await self.session.flush()
            await self._notify_owner_dead_order_payment(order, payment)
            return payment

        # Check if order already has a PAID payment
        existing_paid = await self.payment_repo.get_by_order_id(order_id)
        if existing_paid and existing_paid.status == PaymentStatus.PAID.value:
            # Different charge ID for an already PAID order: record as REFUND_PENDING / DUPLICATE_CHARGE
            payment = await self.payment_repo.create_payment(
                order_id=order.id,
                barber_id=order.barber_id,
                client_id=order.client_id,
                amount=payment_amount_uzs,
                method=method,
                provider_payment_id=provider_payment_id,
                status=PaymentStatus.REFUND_PENDING.value,
                raw_payload=raw_payload,
            )
            payment.refund_reason = "DUPLICATE_CHARGE"
            await self.session.flush()
            await self._notify_owner_duplicate_payment(order, payment)
            return payment

        # Normal first payment
        if existing_paid and existing_paid.status == PaymentStatus.PENDING.value:
            existing_paid.method = method
            existing_paid.provider_payment_id = provider_payment_id
            payment = await self.payment_repo.mark_as_paid(
                existing_paid, paid_at=current_time, raw_payload=raw_payload
            )
        else:
            payment = await self.payment_repo.create_payment(
                order_id=order.id,
                barber_id=order.barber_id,
                client_id=order.client_id,
                amount=payment_amount_uzs,
                method=method,
                provider_payment_id=provider_payment_id,
                status=PaymentStatus.PAID.value,
                raw_payload=raw_payload,
            )
            payment.paid_at = current_time

        await self.session.flush()

        # If order was PENDING_PAYMENT, activate it now!
        if order.status == OrderStatus.PENDING_PAYMENT.value:
            qs = QueueService(self.session, notifier=self.notifier)
            await qs.activate_prepaid_order(order.id)

        # Immediate notification to barber
        amount_fmt = format_money(payment_amount_uzs)
        nick = order.client_display_name
        barber = await self.barber_repo.get_by_id(order.barber_id)
        if barber and barber.user:
            await self.notifier.notify_barber_payment(
                barber_tg_id=barber.user.telegram_id,
                barber_lang=barber.user.language,
                nick=nick,
                amount_fmt=amount_fmt,
                method=method,
            )

        # Receipt notification to client
        if order.client:
            client_text = t(
                "client.payment_receipt",
                lang=order.client.language,
                amount=amount_fmt,
                method=method,
            )
            await self.notifier.send_message(
                telegram_id=order.client.telegram_id,
                text=client_text,
            )

        await self.audit_repo.log(
            actor_user_id=order.client_id,
            action="PAYMENT_RECEIVED",
            entity="Payment",
            entity_id=str(payment.id),
            data={
                "method": method,
                "amount": payment_amount_uzs,
                "provider_id": provider_payment_id,
            },
        )
        return payment

    async def confirm_cash_payment(self, order_id: int, barber_user_id: int) -> Payment:
        """Barber confirms cash payment ('Naqd to'landi')."""
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise PaymentException("Order not found")

        provider_tx_id = f"cash_{order.id}_{int(now_utc().timestamp())}"
        payment = await self.handle_successful_payment(
            method=PaymentMethod.CASH.value,
            provider_payment_id=provider_tx_id,
            amount=order.price,
            order_id=order.id,
            raw_payload={"confirmed_by_barber_user_id": barber_user_id},
        )
        return payment

    async def mark_refund_done(self, payment_id: int, owner_user_id: int) -> Payment:
        """Owner marks a refund as completed ('Qaytarildi')."""
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise PaymentException("Payment not found")

        await self.payment_repo.mark_as_refunded(payment)
        await self.audit_repo.log(
            actor_user_id=owner_user_id,
            action="REFUND_COMPLETED",
            entity="Payment",
            entity_id=str(payment.id),
            data={"amount": payment.amount, "method": payment.method},
        )
        return payment

    async def _notify_owner_duplicate_payment(self, order: Order, payment: Payment) -> None:
        amount_fmt = format_money(payment.amount)
        for owner_id in settings.OWNER_TELEGRAM_IDS:
            text = t(
                "payments.refund_duplicate_notify_owner",
                "uz",
                order_id=order.id,
                charge_id=payment.provider_payment_id,
                amount=amount_fmt,
                method=payment.method,
            )
            await self.notifier.send_message(owner_id, text)

    async def _notify_owner_dead_order_payment(self, order: Order, payment: Payment) -> None:
        amount_fmt = format_money(payment.amount)
        for owner_id in settings.OWNER_TELEGRAM_IDS:
            text = t(
                "payments.refund_pending_notify_owner",
                "uz",
                order_id=order.id,
                amount=amount_fmt,
                method=payment.method,
            )
            await self.notifier.send_message(owner_id, text)

