from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.i18n import t
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.models.order import Order
from app.models.payment import Payment
from app.payments import get_payment_providers
from app.repositories.audit_repo import AuditRepository
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.user_repo import UserRepository
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


def is_retryable_concurrency_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    if "deadlock detected" in msg or "could not serialize" in msg or "40p01" in msg or "40001" in msg:
        return True
    orig = getattr(exc, "orig", None)
    if orig:
        sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
        if sqlstate in ("40P01", "40001"):
            return True
        orig_msg = str(orig).lower()
        if "deadlock detected" in orig_msg or "could not serialize" in orig_msg:
            return True
    return False


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
        self.user_repo = UserRepository(session)
        self.providers = get_payment_providers()

    async def get_or_create_pending_payment(
        self, order_id: int, method: str
    ) -> tuple[Payment, dict[str, Any]]:
        """Get or initiate a payment for an order with a chosen method."""
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise PaymentException(f"Order #{order_id} not found")

        # N1: Take barber lock first
        await self.barber_repo.lock_barber_for_update(order.barber_id)

        # N1: Re-read order with populate_existing=True
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
        Idempotent payment confirmation handler with concurrency retry loop:
        - Locks barber row first to enforce global lock order
        - Checks uniqueness on (method, provider_payment_id)
        - Verifies amount against order price (records refund on mismatch)
        - Marks payment as PAID
        - If order was PENDING_PAYMENT, activates order into queue
        - Notifies barber with client nick, amount, method
        - Notifies client with receipt
        """
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                return await self._execute_successful_payment(
                    method=method,
                    provider_payment_id=provider_payment_id,
                    amount=amount,
                    order_id=order_id,
                    raw_payload=raw_payload,
                )
            except Exception as exc:
                if is_retryable_concurrency_error(exc) and attempt < max_attempts - 1:
                    logger.warning(
                        "Concurrency conflict on payment %s:%s (attempt %d/%d): %s. Retrying...",
                        method,
                        provider_payment_id,
                        attempt + 1,
                        max_attempts,
                        exc,
                    )
                    try:
                        await self.session.rollback()
                    except Exception as rb_exc:
                        logger.warning("Rollback failed during retryable concurrency conflict: %s", rb_exc)
                    await asyncio.sleep(0.05 * (2**attempt) + random.uniform(0.01, 0.05))
                    continue

                try:
                    await self.session.rollback()
                except Exception as rb_exc:
                    logger.warning("Rollback failed during critical payment failure: %s", rb_exc)

                logger.critical(
                    "Payment recording failed: method=%s, provider_id=%s, order_id=%s, amount=%s: %s",
                    method,
                    provider_payment_id,
                    order_id,
                    amount,
                    exc,
                )
                try:
                    await self._notify_owners_critical_payment_failure(
                        order_id=order_id,
                        method=method,
                        charge_id=provider_payment_id,
                        amount=amount,
                        error_str=str(exc),
                    )
                except Exception as notify_err:
                    logger.critical("Failed to dispatch critical payment failure alert: %s", notify_err)
                raise

        raise PaymentException(f"Failed to record payment for order #{order_id} after {max_attempts} attempts")

    async def _execute_successful_payment(
        self,
        method: str,
        provider_payment_id: str,
        amount: int,
        order_id: int,
        raw_payload: dict[str, Any] | None = None,
    ) -> Payment:
        # Fast idempotency check before locking
        existing = await self.payment_repo.get_by_provider_id(method, provider_payment_id)
        if existing:
            logger.info(
                "Payment %s:%s already exists (status=%s). Idempotent return.",
                method,
                provider_payment_id,
                existing.status,
            )
            return existing

        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise PaymentException(f"Order #{order_id} not found")

        # N1: Take Barber row FOR UPDATE first before any payment or order update
        await self.barber_repo.lock_barber_for_update(order.barber_id)

        # N1: After taking barber lock, re-read order with populate_existing=True
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise PaymentException(f"Order #{order_id} not found")

        # Re-check idempotency in case it was created while waiting for lock
        existing = await self.payment_repo.get_by_provider_id(method, provider_payment_id)
        if existing:
            logger.info(
                "Payment %s:%s already exists after lock (status=%s). Idempotent return.",
                method,
                provider_payment_id,
                existing.status,
            )
            return existing

        # N1: Amount verification - if amount != order.price, record as REFUND_PENDING with AMOUNT_MISMATCH
        # Note: Telegram payment sends amount in tiyin (amount == order.price * 100)
        is_amount_valid = (amount == order.price) or (amount == order.price * 100)
        if not is_amount_valid:
            logger.warning(
                "Payment amount mismatch for order #%d: received %d, expected %d",
                order.id,
                amount,
                order.price,
            )
            payment = await self.payment_repo.create_payment(
                order_id=order.id,
                barber_id=order.barber_id,
                client_id=order.client_id,
                amount=amount,
                method=method,
                provider_payment_id=provider_payment_id,
                status=PaymentStatus.REFUND_PENDING.value,
                raw_payload=raw_payload,
            )
            payment.refund_reason = "AMOUNT_MISMATCH"
            await self.session.flush()
            await self._notify_owner_amount_mismatch(order, payment, order.price)
            return payment

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
        paid_payment = await self.payment_repo.get_paid_by_order_id(order_id)
        if paid_payment:
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
        existing_pending = await self.payment_repo.get_by_order_id(order_id)
        try:
            if existing_pending and existing_pending.status == PaymentStatus.PENDING.value:
                existing_pending.method = method
                existing_pending.provider_payment_id = provider_payment_id
                payment = await self.payment_repo.mark_as_paid(
                    existing_pending, paid_at=current_time, raw_payload=raw_payload
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
        except IntegrityError:
            await self.session.rollback()
            await self.barber_repo.lock_barber_for_update(order.barber_id)
            order = await self.order_repo.get_by_id(order_id)
            existing_charge = await self.payment_repo.get_by_provider_id(method, provider_payment_id)
            if existing_charge:
                return existing_charge
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

        # N1: Take barber lock first
        await self.barber_repo.lock_barber_for_update(order.barber_id)

        # N1: Re-read order
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise PaymentException("Order not found")

        # N2: only allow cash payment for COMPLETED orders
        if order.status != OrderStatus.COMPLETED.value:
            raise PaymentException(f"Order #{order_id} cannot accept cash payment in status {order.status}")

        # Idempotency check: if already paid, return existing payment without duplicate row
        existing_paid = await self.payment_repo.get_paid_by_order_id(order_id)
        if existing_paid:
            return existing_paid

        provider_tx_id = f"cash_{order.id}"
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

    async def _get_owner_lang(self, owner_id: int) -> str:
        try:
            owner_user = await self.user_repo.get_by_telegram_id(owner_id)
            if owner_user and owner_user.language:
                return owner_user.language
        except Exception as exc:
            logger.warning("Failed to fetch language for owner %s, fallback to 'uz': %s", owner_id, exc)
        return "uz"

    async def _notify_owner_duplicate_payment(self, order: Order, payment: Payment) -> None:
        amount_fmt = format_money(payment.amount)
        for owner_id in settings.OWNER_TELEGRAM_IDS:
            lang = await self._get_owner_lang(owner_id)
            text = t(
                "payments.refund_duplicate_notify_owner",
                lang,
                order_id=order.id,
                charge_id=payment.provider_payment_id,
                amount=amount_fmt,
                method=payment.method,
            )
            await self.notifier.send_message(owner_id, text)

    async def _notify_owner_dead_order_payment(self, order: Order, payment: Payment) -> None:
        amount_fmt = format_money(payment.amount)
        for owner_id in settings.OWNER_TELEGRAM_IDS:
            lang = await self._get_owner_lang(owner_id)
            text = t(
                "payments.refund_pending_notify_owner",
                lang,
                order_id=order.id,
                amount=amount_fmt,
                method=payment.method,
            )
            await self.notifier.send_message(owner_id, text)

    async def _notify_owner_amount_mismatch(self, order: Order, payment: Payment, expected: int) -> None:
        amount_fmt = format_money(payment.amount)
        expected_fmt = format_money(expected)
        for owner_id in settings.OWNER_TELEGRAM_IDS:
            lang = await self._get_owner_lang(owner_id)
            text = t(
                "payments.amount_mismatch_notify_owner",
                lang,
                order_id=order.id,
                charge_id=payment.provider_payment_id,
                amount=amount_fmt,
                expected=expected_fmt,
            )
            await self.notifier.send_message(owner_id, text)

    async def _notify_owners_critical_payment_failure(
        self, order_id: int, method: str, charge_id: str, amount: int, error_str: str
    ) -> None:
        try:
            amount_fmt = format_money(amount)
            for owner_id in settings.OWNER_TELEGRAM_IDS:
                lang = await self._get_owner_lang(owner_id)
                text = t(
                    "payments.critical_failure_notify_owner",
                    lang,
                    order_id=order_id,
                    charge_id=charge_id,
                    amount=amount_fmt,
                    method=method,
                    error=error_str[:100],
                )
                await self.notifier.send_message(owner_id, text)
        except Exception as exc:
            logger.critical("Unexpected error in _notify_owners_critical_payment_failure: %s", exc)
