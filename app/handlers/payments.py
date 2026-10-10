from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n import t
from app.models.enums import OrderStatus, PaymentStatus
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.notification_service import NotificationService
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)
router = Router(name="payments_router")


@router.pre_checkout_query()
async def handle_pre_checkout(query: PreCheckoutQuery, session: AsyncSession):
    lang = "uz"

    # 1. Currency validation (must be UZS)
    if query.currency != "UZS":
        await query.answer(ok=False, error_message=t("payments.err_currency_uzs", lang=lang))
        return

    # 2. Payload format validation (e.g. "order_12_CLICK")
    payload = query.invoice_payload or ""
    parts = payload.split("_")
    if len(parts) < 3 or parts[0] != "order" or not parts[1].isdigit():
        await query.answer(ok=False, error_message=t("payments.err_malformed_payload", lang=lang))
        return

    order_id = int(parts[1])

    # 3. Order existence
    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order:
        await query.answer(ok=False, error_message=t("payments.err_order_not_found", lang=lang))
        return

    if order.client:
        lang = order.client.language

    # 4. Payer must be the order's client
    if order.client and order.client.telegram_id != query.from_user.id:
        await query.answer(ok=False, error_message=t("payments.err_foreign_payer", lang=lang))
        return

    # 5. Order status check (not cancelled or expired)
    if order.status in [
        OrderStatus.CANCELLED_BY_CLIENT.value,
        OrderStatus.CANCELLED_BY_STAFF.value,
        OrderStatus.CANCELLED_NO_SHOW.value,
        OrderStatus.EXPIRED.value,
    ]:
        await query.answer(ok=False, error_message=t("payments.err_order_cancelled", lang=lang))
        return

    # 6. Check if order already has a PAID payment
    pay_repo = PaymentRepository(session)
    existing_paid = await pay_repo.get_by_order_id(order.id)
    if existing_paid and existing_paid.status == PaymentStatus.PAID.value:
        await query.answer(ok=False, error_message=t("payments.err_already_paid", lang=lang))
        return

    # 7. Exact amount verification in tiyin (total_amount == price * 100)
    expected_amount = order.price * 100
    if query.total_amount != expected_amount:
        await query.answer(ok=False, error_message=t("payments.err_amount_mismatch", lang=lang))
        return

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment_msg(message: Message, session: AsyncSession, bot: Bot):
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload  # "order_12_CLICK"
    parts = payload.split("_")
    order_id = int(parts[1])
    method = parts[2]

    provider_tx_id = (
        payment_info.provider_payment_charge_id or payment_info.telegram_payment_charge_id
    )
    # Convert from tiyin to UZS
    amount_uzs = payment_info.total_amount // 100

    payment_service = PaymentService(session, notifier=NotificationService(bot=bot))
    await payment_service.handle_successful_payment(
        method=method,
        provider_payment_id=provider_tx_id,
        amount=amount_uzs,
        order_id=order_id,
        raw_payload={
            "telegram_payment_charge_id": payment_info.telegram_payment_charge_id,
            "provider_payment_charge_id": payment_info.provider_payment_charge_id,
        },
    )
    await session.commit()
