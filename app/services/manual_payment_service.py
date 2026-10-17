"""Manual card-transfer payments (TRANSFER).

Flow: the client pays to the barbershop card, sends a PHOTO of the bank receipt, the serving barber (or the owner) looks at the photo
and presses Confirm or Reject. Nothing here blocks the queue: the client is already in the queue, payment is a separate record.

Money-safety rules (all covered by tests/test_manual_payments.py):
- every state change takes the per-barber row lock FIRST and re-reads the payment afterwards (same rule as PaymentService);
- confirming twice (two staff members, double tap) records the money once;
- one receipt photo (Telegram file_unique_id) can back only one payment;
- a receipt for an order that was cancelled meanwhile becomes REFUND_PENDING and the owner is told;
- if the order was paid in cash meanwhile, the transferred money becomes REFUND_PENDING and the owner is told.
"""
from __future__ import annotations

import html
import logging
from typing import NamedTuple

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.i18n import t
from app.keyboards.common import btn
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.models.payment import Payment
from app.models.user import User
from app.repositories.audit_repo import AuditRepository
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.user_repo import UserRepository
from app.services.authorization import assert_can_manage_order
from app.services.notification_service import NotificationService
from app.utils.formatting import format_money
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

PAYABLE_ORDER_STATUSES = (
    OrderStatus.WAITING.value,
    OrderStatus.CALLED.value,
    OrderStatus.IN_SERVICE.value,
    OrderStatus.COMPLETED.value,
)
DEAD_ORDER_STATUSES = (
    OrderStatus.CANCELLED_BY_CLIENT.value,
    OrderStatus.CANCELLED_BY_STAFF.value,
    OrderStatus.CANCELLED_NO_SHOW.value,
    OrderStatus.EXPIRED.value,
)
REJECT_REASONS = ("AMOUNT", "UNCLEAR", "NOT_RECEIVED")


def build_receipt_review_keyboard(payment_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            btn(text=t("payments.btn_transfer_ok", lang=lang), callback_data=f"tr_ok:{payment_id}", style="success", icon="check"),
            btn(text=t("payments.btn_transfer_no", lang=lang), callback_data=f"tr_no:{payment_id}", style="danger", icon="cross"),
        ]
    ])


class ManualPaymentError(Exception):
    """Base class. `code` is a stable machine-readable reason for the handlers."""

    code = "ERROR"


class OrderNotPayableError(ManualPaymentError):
    code = "ORDER_NOT_PAYABLE"


class AlreadyPaidError(ManualPaymentError):
    code = "ALREADY_PAID"


class DuplicateReceiptError(ManualPaymentError):
    code = "DUPLICATE_RECEIPT"


class NothingToConfirmError(ManualPaymentError):
    code = "NOTHING_TO_CONFIRM"


class TransferResult(NamedTuple):
    payment: Payment
    changed: bool
    refund_flagged: bool = False


class ManualPaymentService:
    def __init__(self, session: AsyncSession, notifier: NotificationService | None = None):
        self.session = session
        self.notifier = notifier or NotificationService()
        self.order_repo = OrderRepository(session)
        self.barber_repo = BarberRepository(session)
        self.payment_repo = PaymentRepository(session)
        self.user_repo = UserRepository(session)
        self.audit_repo = AuditRepository(session)

    # ------------------------------------------------------------------ helpers
    async def _transfer_row(self, order_id: int) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.order_id == order_id, Payment.method == PaymentMethod.TRANSFER.value)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _owner_lang(self, owner_tg_id: int) -> str:
        try:
            owner = await self.user_repo.get_by_telegram_id(owner_tg_id)
            if owner and owner.language:
                return owner.language
        except Exception as exc:  # never let an alert fail because of a language lookup
            logger.warning("owner language lookup failed for %s: %s", owner_tg_id, exc)
        return "uz"

    async def _alert_owners(self, key: str, **kwargs) -> None:
        for owner_id in settings.OWNER_TELEGRAM_IDS:
            try:
                lang = await self._owner_lang(owner_id)
                await self.notifier.send_message(owner_id, t(key, lang=lang, **kwargs))
            except Exception as exc:
                logger.critical("Failed to alert owner %s (%s): %s", owner_id, key, exc)

    # ------------------------------------------------------------------ client side
    async def submit_receipt(
        self, order_id: int, client_user_id: int, file_id: str, file_unique_id: str
    ) -> Payment:
        """Client sends (or re-sends) the receipt photo for his own order. Does not block the queue."""
        order = await self.order_repo.get_by_id(order_id)
        if not order or order.client_id != client_user_id:
            raise OrderNotPayableError("order not found or not yours")

        await self.barber_repo.lock_barber_for_update(order.barber_id)  # lock FIRST
        order = await self.order_repo.get_by_id(order_id)  # re-read after the lock
        if not order or order.client_id != client_user_id or order.status not in PAYABLE_ORDER_STATUSES:
            raise OrderNotPayableError("order cannot be paid in its current state")

        if await self.payment_repo.get_paid_by_order_id(order.id):
            raise AlreadyPaidError("order already paid")

        payment = await self._transfer_row(order.id)
        if payment is not None and payment.status not in (
            PaymentStatus.PENDING.value, PaymentStatus.REJECTED.value, PaymentStatus.RECEIPT_SENT.value
        ):
            raise OrderNotPayableError(f"transfer payment is {payment.status}")

        clash = (
            await self.session.execute(
                select(Payment.id).where(Payment.receipt_file_unique_id == file_unique_id)
            )
        ).scalars().first()
        if clash is not None and (payment is None or clash != payment.id):
            raise DuplicateReceiptError("this receipt was already used for another payment")

        try:
            async with self.session.begin_nested():
                if payment is None:
                    payment = Payment(
                        order_id=order.id,
                        barber_id=order.barber_id,
                        client_id=order.client_id,
                        amount=order.price,
                        method=PaymentMethod.TRANSFER.value,
                        provider_payment_id=f"transfer_{order.id}",
                        status=PaymentStatus.RECEIPT_SENT.value,
                    )
                    self.session.add(payment)
                payment.status = PaymentStatus.RECEIPT_SENT.value
                payment.receipt_file_id = file_id
                payment.receipt_file_unique_id = file_unique_id
                payment.receipt_sent_at = now_utc()
                await self.session.flush()
        except IntegrityError as exc:
            raise DuplicateReceiptError("this receipt was already used for another payment") from exc

        await self.audit_repo.log(
            actor_user_id=client_user_id,
            action="TRANSFER_RECEIPT_SUBMITTED",
            entity="Payment",
            entity_id=str(payment.id),
            data={"order_id": order.id, "amount": payment.amount},
        )
        return payment

    # ------------------------------------------------------------------ staff side
    async def _load_for_staff(self, payment_id: int, staff: User, barber) -> Payment:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment or payment.method != PaymentMethod.TRANSFER.value:
            raise NothingToConfirmError("payment not found")
        assert_can_manage_order(staff, payment.order, barber=barber)  # raises AuthorizationError
        await self.barber_repo.lock_barber_for_update(payment.barber_id)  # lock FIRST
        payment = await self.payment_repo.get_by_id(payment_id)  # re-read after the lock
        if not payment:
            raise NothingToConfirmError("payment not found")
        return payment

    async def confirm_transfer(self, payment_id: int, staff: User, barber=None) -> TransferResult:
        """Staff looked at the photo and confirms the money arrived. Idempotent."""
        payment = await self._load_for_staff(payment_id, staff, barber)
        if payment.status == PaymentStatus.PAID.value:
            return TransferResult(payment, False)
        if payment.status != PaymentStatus.RECEIPT_SENT.value:
            raise NothingToConfirmError(f"payment is {payment.status}")

        order = await self.order_repo.get_by_id(payment.order_id)

        # The order was cancelled while the receipt was waiting: the money did arrive -> the owner must refund it
        if order is None or order.status in DEAD_ORDER_STATUSES:
            return await self._flag_refund(payment, order, staff, "ORDER_CANCELLED")

        # Someone already recorded a payment for this order (e.g. cash): the transfer is a duplicate -> refund it
        if await self.payment_repo.get_paid_by_order_id(payment.order_id):
            return await self._flag_refund(payment, order, staff, "DUPLICATE_PAYMENT")

        try:
            async with self.session.begin_nested():
                payment.status = PaymentStatus.PAID.value
                payment.paid_at = now_utc()
                payment.confirmed_by_user_id = staff.id
                await self.session.flush()
        except IntegrityError:
            # lost a race against another PAID row for this order (uq_one_paid_per_order)
            await self.session.refresh(payment)
            return await self._flag_refund(payment, order, staff, "DUPLICATE_PAYMENT")

        await self.audit_repo.log(
            actor_user_id=staff.id,
            action="TRANSFER_CONFIRMED",
            entity="Payment",
            entity_id=str(payment.id),
            data={"order_id": payment.order_id, "amount": payment.amount, "barber_id": payment.barber_id},
        )
        return TransferResult(payment, True)

    async def _flag_refund(self, payment: Payment, order, staff: User, reason: str) -> TransferResult:
        payment.status = PaymentStatus.REFUND_PENDING.value
        payment.refund_reason = reason
        payment.confirmed_by_user_id = staff.id
        await self.session.flush()
        await self.audit_repo.log(
            actor_user_id=staff.id,
            action="TRANSFER_REFUND_FLAGGED",
            entity="Payment",
            entity_id=str(payment.id),
            data={"order_id": payment.order_id, "reason": reason},
        )
        await self._alert_owners(
            "payments.transfer_refund_owner",
            order_id=payment.order_id,
            amount=format_money(payment.amount),
            reason=reason,
        )
        return TransferResult(payment, True, refund_flagged=True)

    async def reject_transfer(self, payment_id: int, staff: User, reason: str, barber=None) -> TransferResult:
        """Staff rejects the receipt (wrong amount / unreadable / money not received). The client may send a new one."""
        if reason not in REJECT_REASONS:
            raise ManualPaymentError(f"unknown reject reason {reason!r}")
        payment = await self._load_for_staff(payment_id, staff, barber)
        if payment.status == PaymentStatus.REJECTED.value:
            return TransferResult(payment, False)
        if payment.status != PaymentStatus.RECEIPT_SENT.value:
            raise NothingToConfirmError(f"payment is {payment.status}")

        history = list((payment.raw_payload or {}).get("rejections", []))
        history.append({"at": now_utc().isoformat(), "by": staff.id, "reason": reason,
                        "receipt": payment.receipt_file_unique_id})
        payment.raw_payload = {**(payment.raw_payload or {}), "rejections": history}
        payment.status = PaymentStatus.REJECTED.value
        await self.session.flush()
        await self.audit_repo.log(
            actor_user_id=staff.id,
            action="TRANSFER_REJECTED",
            entity="Payment",
            entity_id=str(payment.id),
            data={"order_id": payment.order_id, "reason": reason},
        )
        return TransferResult(payment, True)

    # ------------------------------------------------------------------ notifications (call AFTER commit)
    async def notify_receipt_submitted(self, payment_id: int) -> bool:
        """Send the receipt photo to the order's barber with Confirm / Reject buttons; fall back to the owners."""
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment or not payment.receipt_file_id:
            return False
        order = payment.order
        barber = payment.barber
        barber_user = await self.user_repo.get_by_id(barber.user_id) if barber else None

        def build(lang: str) -> tuple[str, InlineKeyboardMarkup]:
            nick = html.escape(order.client_display_name) if order else "?"
            caption = t(
                "payments.transfer_review_caption",
                lang=lang,
                nick=nick,
                ticket_no=order.ticket_no if order else "?",
                service=html.escape(order.service_name) if order else "?",
                amount=format_money(payment.amount),
            )
            kb = build_receipt_review_keyboard(payment.id, lang=lang)
            return caption, kb

        sent = False
        if barber_user is not None:
            caption, kb = build(barber_user.language or "uz")
            sent = await self.notifier.send_photo(
                barber_user.telegram_id, payment.receipt_file_id, caption, reply_markup=kb, parse_mode="HTML"
            )
        if not sent:  # barber unreachable (blocked the bot / no account): the owners decide
            for owner_id in settings.OWNER_TELEGRAM_IDS:
                caption, kb = build(await self._owner_lang(owner_id))
                sent = await self.notifier.send_photo(
                    owner_id, payment.receipt_file_id, caption, reply_markup=kb, parse_mode="HTML"
                ) or sent
        return sent

    async def notify_client_confirmed(self, payment: Payment) -> None:
        client = payment.client
        if client:
            await self.notifier.send_message(
                client.telegram_id,
                t("payments.transfer_confirmed_client", lang=client.language, amount=format_money(payment.amount)),
            )

    async def notify_client_rejected(self, payment: Payment, reason: str) -> None:
        client = payment.client
        if not client:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            btn(
                text=t("payments.btn_send_receipt", lang=client.language),
                callback_data=f"tr_send:{payment.order_id}",
                style="primary",
                icon="attach",
            )
        ]])
        await self.notifier.send_message(
            client.telegram_id,
            t(f"payments.transfer_rejected_{reason.lower()}", lang=client.language, amount=format_money(payment.amount)),
            reply_markup=kb,
        )

