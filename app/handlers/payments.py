from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus
from app.repositories.order_repo import OrderRepository
from app.services.notification_service import NotificationService
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)
router = Router(name="payments_router")


@router.pre_checkout_query()
async def handle_pre_checkout(query: PreCheckoutQuery, session: AsyncSession):
    payload = query.invoice_payload  # e.g. "order_12_CLICK"
    parts = payload.split("_")
    if len(parts) < 3 or parts[0] != "order":
        await query.answer(ok=False, error_message="Buyurtma ma'lumotlari xato.")
        return

    order_id = int(parts[1])
    parts[2]

    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id)
    if not order:
        await query.answer(ok=False, error_message="Buyurtma topilmadi.")
        return

    if order.status in [
        OrderStatus.CANCELLED_BY_CLIENT.value,
        OrderStatus.CANCELLED_BY_STAFF.value,
        OrderStatus.CANCELLED_NO_SHOW.value,
        OrderStatus.EXPIRED.value,
    ]:
        await query.answer(ok=False, error_message="Ushbu buyurtma bekor qilingan.")
        return

    # In Telegram payments, amount is in smallest unit (tiyin: order.price * 100)
    expected_amount = order.price * 100
    if query.total_amount != expected_amount:
        await query.answer(ok=False, error_message="To'lov miqdori mos kelmadi.")
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
