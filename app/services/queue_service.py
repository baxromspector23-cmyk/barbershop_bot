from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.i18n import t
from app.models.barber import Barber
from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.models.user import User
from app.repositories.audit_repo import AuditRepository
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.notification_service import NotificationService
from app.utils.formatting import format_money
from app.utils.time_utils import (
    now_tashkent,
    now_utc,
    tashkent_today,
)

logger = logging.getLogger(__name__)


class QueueException(Exception):
    pass


class AlreadyInQueueError(QueueException):
    pass


class BarberClosedError(QueueException):
    pass


class CannotCancelInServiceError(QueueException):
    pass


class TransitionResult(tuple):
    def __new__(cls, order: Order | None, changed: bool):
        return super().__new__(cls, (order, changed))

    @property
    def order(self) -> Order | None:
        return self[0]

    @property
    def changed(self) -> bool:
        return self[1]

    def __bool__(self) -> bool:
        return self[0] is not None

    def __getattr__(self, name: str) -> Any:
        if self[0] is not None and hasattr(self[0], name):
            return getattr(self[0], name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


class QueueService:
    _barber_locks: dict[int, asyncio.Lock] = {}

    @classmethod
    def get_lock(cls, barber_id: int) -> asyncio.Lock:
        if barber_id not in cls._barber_locks:
            cls._barber_locks[barber_id] = asyncio.Lock()
        return cls._barber_locks[barber_id]

    def __init__(
        self,
        session: AsyncSession,
        notifier: NotificationService | None = None,
    ):
        self.session = session
        self.notifier = notifier or NotificationService()
        self.barber_repo = BarberRepository(session)
        self.order_repo = OrderRepository(session)
        self.payment_repo = PaymentRepository(session)
        self.audit_repo = AuditRepository(session)

    # ---------------------------------------------------------
    # Metrics & Estimation
    # ---------------------------------------------------------
    def calculate_active_wait_time(self, active_orders: list[Order]) -> int:
        """Sum of remaining durations of active orders ahead."""
        current_time = now_utc()
        total_wait = 0
        for o in active_orders:
            if o.status == OrderStatus.IN_SERVICE.value:
                if o.started_at:
                    elapsed = max(0, int((current_time - o.started_at).total_seconds() / 60))
                    total_wait += max(0, o.duration_minutes - elapsed)
                else:
                    total_wait += o.duration_minutes
            else:
                total_wait += o.duration_minutes
        return total_wait

    async def get_barber_queue_metrics(self, barber_id: int) -> tuple[int, int]:
        """Returns (queue_length, estimated_wait_minutes)."""
        active_orders = await self.order_repo.get_active_orders_for_barber(barber_id)
        queue_len = len(active_orders)
        est_wait = self.calculate_active_wait_time(active_orders)
        return queue_len, est_wait

    def is_barber_open(self, barber: Barber, estimated_wait_minutes: int) -> bool:
        """
        Check if barber is active, not paused, and within working hours.
        Also check that estimated start time is before closing time.
        """
        if not barber.is_active or barber.is_paused:
            return False

        current_tashkent = now_tashkent()
        current_time = current_tashkent.time()
        weekday = current_tashkent.weekday()

        # Find today's working hours
        wh = next((h for h in barber.working_hours if h.weekday == weekday), None)
        if not wh or wh.is_day_off:
            return False

        if current_time < wh.start_time or current_time >= wh.end_time:
            return False

        # Check estimated start time against closing time
        est_start = (current_tashkent + timedelta(minutes=estimated_wait_minutes)).time()
        if est_start >= wh.end_time:
            return False

        return True

    def calculate_order_position_and_wait(
        self, target_order: Order, active_orders: list[Order]
    ) -> tuple[int, int, int]:
        """
        Returns (position, people_ahead, estimated_wait_minutes)
        Position of an order = count of active orders of same barber with smaller position_key + 1
        """
        ahead_orders = [o for o in active_orders if o.position_key < target_order.position_key]
        people_ahead = len(ahead_orders)
        position = people_ahead + 1
        est_wait = self.calculate_active_wait_time(ahead_orders)
        return position, people_ahead, est_wait

    # ---------------------------------------------------------
    # Core State Machine Operations
    # ---------------------------------------------------------
    async def join_queue(
        self,
        barber_id: int,
        service_id: int,
        client: User | None = None,
        walkin_name: str | None = None,
        walkin_phone: str | None = None,
        pay_now: bool = False,
    ) -> Order:
        """
        Join queue:
        - Locks barber row
        - Checks barber open status and existing client active order
        - Snapshots service price, duration, and name
        - Assigns position_key and daily ticket_no
        - Calls client immediately if barber is free and not pay_now
        """
        lock = self.get_lock(barber_id)
        async with lock:
            barber = await self.barber_repo.lock_barber_for_update(barber_id)
            if not barber:
                raise QueueException(f"Barber #{barber_id} not found")

            # Check client active order
            if client:
                active_existing = await self.order_repo.get_active_order_for_client(client.id)
                if active_existing:
                    raise AlreadyInQueueError("Client already has an active order")

            # Get active orders to check queue wait & schedule
            active_orders = await self.order_repo.get_active_orders_for_barber(barber_id)
            est_wait = self.calculate_active_wait_time(active_orders)

            if not self.is_barber_open(barber, est_wait):
                raise BarberClosedError("Barber is currently unavailable or closed")

            # Fetch service
            service = await self.barber_repo.get_service_by_id(service_id)
            if not service or service.barber_id != barber_id:
                raise QueueException(f"Service #{service_id} not valid for barber #{barber_id}")

            next_pos_key = await self.order_repo.get_next_position_key(barber_id)
            today_date = tashkent_today()
            next_ticket = await self.order_repo.get_next_ticket_no(barber_id, today_date)

            initial_status = (
                OrderStatus.PENDING_PAYMENT.value if pay_now else OrderStatus.WAITING.value
            )

            order = Order(
                barber_id=barber_id,
                client_id=client.id if client else None,
                walkin_name=walkin_name,
                walkin_phone=walkin_phone,
                service_id=service.id,
                service_name=service.name,
                price=service.price,
                duration_minutes=service.duration_minutes,
                status=initial_status,
                position_key=next_pos_key,
                ticket_no=next_ticket,
                ticket_date=today_date,
                late_count=0,
                heads_up_sent=False,
                created_at=now_utc(),
            )
            self.session.add(order)
            await self.session.flush()

            # If paying later (enters queue immediately)
            if not pay_now:
                await self._on_order_entered_queue(order, barber, active_orders)

            await self.audit_repo.log(
                actor_user_id=client.id if client else None,
                action="ORDER_JOINED",
                entity="Order",
                entity_id=str(order.id),
                data={
                    "barber_id": barber_id,
                    "ticket_no": next_ticket,
                    "status": initial_status,
                    "pay_now": pay_now,
                },
            )
            return order

    async def activate_prepaid_order(self, order_id: int) -> Order:
        """Transition PENDING_PAYMENT -> WAITING and handle calling/heads-up."""
        order = await self.order_repo.get_by_id(order_id)
        if not order or order.status != OrderStatus.PENDING_PAYMENT.value:
            return order

        barber = await self.barber_repo.lock_barber_for_update(order.barber_id)
        active_orders = await self.order_repo.get_active_orders_for_barber(order.barber_id)

        # Update position key to current end of queue to preserve arrival ordering
        order.position_key = await self.order_repo.get_next_position_key(order.barber_id)
        order.status = OrderStatus.WAITING.value
        await self.session.flush()

        await self._on_order_entered_queue(order, barber, active_orders)

        await self.audit_repo.log(
            actor_user_id=order.client_id,
            action="ORDER_ACTIVATED_POST_PAYMENT",
            entity="Order",
            entity_id=str(order.id),
        )
        return order

    async def _on_order_entered_queue(
        self, order: Order, barber: Barber, active_orders_before: list[Order]
    ) -> None:
        """Handle calling or heads-up notification when an order enters the active queue."""
        # Check if barber is free: no order in CALLED or IN_SERVICE
        has_busy_order = any(
            o.status in [OrderStatus.CALLED.value, OrderStatus.IN_SERVICE.value]
            for o in active_orders_before
        )

        # Recalculate position
        new_active = await self.order_repo.get_active_orders_for_barber(barber.id)
        pos, ahead, est_wait = self.calculate_order_position_and_wait(order, new_active)

        # Alert barber of new client
        if barber.user:
            nick = order.client_display_name
            await self.notifier.notify_barber_new_client(
                barber_tg_id=barber.user.telegram_id,
                barber_lang=barber.user.language,
                nick=nick,
                service=order.service_name,
                pos=pos,
            )

        if not has_busy_order and pos == 1:
            # Free barber: call immediately!
            await self._call_order(order, barber)
        else:
            # Check heads-up
            if ahead == settings.HEADS_UP_AHEAD and not order.heads_up_sent:
                await self._send_heads_up(order, barber, ahead)

    async def _call_order(self, order: Order, barber: Barber) -> None:
        """Mark order as CALLED, set 10-minute deadline, and notify client."""
        current_utc = now_utc()
        order.status = OrderStatus.CALLED.value
        order.called_at = current_utc
        order.deadline_at = current_utc + timedelta(minutes=settings.LATE_MINUTES)
        await self.session.flush()

        if order.client:
            await self.notifier.notify_client_called(
                client_tg_id=order.client.telegram_id,
                client_lang=order.client.language,
                barber_name=barber.display_name,
            )

    async def _send_heads_up(self, order: Order, barber: Barber, ahead_count: int) -> None:
        """Send 1-person-ahead heads-up message once per order."""
        if order.heads_up_sent:
            return
        order.heads_up_sent = True
        await self.session.flush()

        if order.client:
            await self.notifier.notify_client_heads_up(
                client_tg_id=order.client.telegram_id,
                client_lang=order.client.language,
                ahead_count=ahead_count,
                barber_name=barber.display_name,
            )

    async def call_next_if_free(self, barber_id: int) -> Order | None:
        """Call the next WAITING order if barber is currently free."""
        barber = await self.barber_repo.lock_barber_for_update(barber_id)
        if not barber:
            return None

        active_orders = await self.order_repo.get_active_orders_for_barber(barber_id)
        has_busy_order = any(
            o.status in [OrderStatus.CALLED.value, OrderStatus.IN_SERVICE.value]
            for o in active_orders
        )
        if has_busy_order:
            return None

        next_order = await self.order_repo.get_next_waiting_order(barber_id)
        if not next_order:
            return None

        await self._call_order(next_order, barber)

        # Update heads-up for remaining queue
        await self.check_and_send_heads_up_for_barber(barber_id)
        return next_order

    async def check_and_send_heads_up_for_barber(self, barber_id: int) -> None:
        """Check all WAITING orders for barber and send heads-up to the one with ahead == HEADS_UP_AHEAD."""
        barber = await self.barber_repo.get_by_id(barber_id)
        if not barber:
            return
        active_orders = await self.order_repo.get_active_orders_for_barber(barber_id)
        for o in active_orders:
            if o.status == OrderStatus.WAITING.value and not o.heads_up_sent:
                pos, ahead, _ = self.calculate_order_position_and_wait(o, active_orders)
                if ahead == settings.HEADS_UP_AHEAD:
                    await self._send_heads_up(o, barber, ahead)

    async def client_arrived(self, order_id: int) -> TransitionResult:
        """Barber clicks 'Keldi' on a CALLED order."""
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            return TransitionResult(None, False)

        await self.barber_repo.lock_barber_for_update(order.barber_id)
        # Re-read order after acquiring barber lock
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            return TransitionResult(None, False)

        # Idempotent: only act if currently CALLED
        if order.status != OrderStatus.CALLED.value:
            return TransitionResult(order, False)

        order.status = OrderStatus.IN_SERVICE.value
        order.started_at = now_utc()
        order.deadline_at = None
        await self.session.flush()

        await self.audit_repo.log(
            actor_user_id=order.barber.user_id if order.barber else None,
            action="CLIENT_ARRIVED",
            entity="Order",
            entity_id=str(order.id),
        )
        return TransitionResult(order, True)

    async def complete_service(self, order_id: int) -> TransitionResult:
        """Barber clicks 'Xizmat ko'rsatildi' on an IN_SERVICE order."""
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            return TransitionResult(None, False)

        await self.barber_repo.lock_barber_for_update(order.barber_id)
        # Re-read order after acquiring barber lock
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            return TransitionResult(None, False)

        # Idempotent: only act if currently IN_SERVICE
        if order.status != OrderStatus.IN_SERVICE.value:
            return TransitionResult(order, False)

        order.status = OrderStatus.COMPLETED.value
        order.completed_at = now_utc()
        await self.session.flush()

        await self.audit_repo.log(
            actor_user_id=order.barber.user_id if order.barber else None,
            action="SERVICE_COMPLETED",
            entity="Order",
            entity_id=str(order.id),
        )

        # Call next client
        await self.call_next_if_free(order.barber_id)
        return TransitionResult(order, True)

    async def handle_lateness(self, order_id: int) -> Order | None:
        """
        Lateness handling (10m deadline elapsed or barber pressed 'Kelmadi'):
        - late_count += 1
        - if late_count <= MAX_LATE_MOVES:
            - swap position_key with immediate next WAITING order
            - set status to WAITING
            - notify client ("moved back")
            - call next order
            - if no one behind: keep CALLED with fresh 10m deadline and notify
        - if late_count > MAX_LATE_MOVES (i.e. 3rd time):
            - CANCELLED_NO_SHOW
            - flag prepaid payments as REFUND_PENDING
            - notify client
            - call next
        """
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            return None

        await self.barber_repo.lock_barber_for_update(order.barber_id)
        if order.status != OrderStatus.CALLED.value:
            return order

        order.late_count += 1
        await self.session.flush()

        if order.late_count <= settings.MAX_LATE_MOVES:
            next_waiting = await self.order_repo.get_next_waiting_after(
                order.barber_id, order.position_key
            )
            if next_waiting:
                # Swap position_key with the next waiting order
                tmp_key = order.position_key
                order.position_key = next_waiting.position_key
                next_waiting.position_key = tmp_key
                order.status = OrderStatus.WAITING.value
                order.called_at = None
                order.deadline_at = None
                await self.session.flush()

                # Calculate new position for late client
                active_orders = await self.order_repo.get_active_orders_for_barber(order.barber_id)
                pos, _, _ = self.calculate_order_position_and_wait(order, active_orders)

                if order.client:
                    await self.notifier.notify_client_moved_back(
                        client_tg_id=order.client.telegram_id,
                        client_lang=order.client.language,
                        new_pos=pos,
                        late_count=order.late_count,
                    )

                # Now call the next order (which is now first)
                await self.call_next_if_free(order.barber_id)
            else:
                # Nobody behind: keep same client CALLED with fresh 10-minute deadline
                current_utc = now_utc()
                order.called_at = current_utc
                order.deadline_at = current_utc + timedelta(minutes=settings.LATE_MINUTES)
                await self.session.flush()

                if order.client:
                    await self.notifier.notify_client_moved_back(
                        client_tg_id=order.client.telegram_id,
                        client_lang=order.client.language,
                        new_pos=1,
                        late_count=order.late_count,
                    )
        else:
            # 3rd no-show: Cancel order
            order.status = OrderStatus.CANCELLED_NO_SHOW.value
            order.cancelled_at = now_utc()
            order.deadline_at = None
            await self.session.flush()

            # Handle refund if prepaid
            await self._flag_refund_if_prepaid(order, reason="CANCELLED_NO_SHOW")

            if order.client:
                await self.notifier.notify_client_cancelled_no_show(
                    client_tg_id=order.client.telegram_id,
                    client_lang=order.client.language,
                )

            # Call next
            await self.call_next_if_free(order.barber_id)

        await self.audit_repo.log(
            actor_user_id=order.client_id,
            action="ORDER_LATENESS_HANDLED",
            entity="Order",
            entity_id=str(order.id),
            data={"late_count": order.late_count, "new_status": order.status},
        )
        return order

    async def cancel_by_client(self, order_id: int, client_id: int) -> Order:
        """Cancel order by client. Not allowed for IN_SERVICE."""
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise QueueException("Order not found")
        if order.client_id != client_id:
            raise QueueException("Permission denied")

        await self.barber_repo.lock_barber_for_update(order.barber_id)

        if order.status == OrderStatus.IN_SERVICE.value:
            raise CannotCancelInServiceError("Cannot cancel an order that is already in service")

        if order.status not in [OrderStatus.WAITING.value, OrderStatus.CALLED.value, OrderStatus.PENDING_PAYMENT.value]:
            return order

        was_called = (order.status == OrderStatus.CALLED.value)
        order.status = OrderStatus.CANCELLED_BY_CLIENT.value
        order.cancelled_at = now_utc()
        order.deadline_at = None
        await self.session.flush()

        await self._flag_refund_if_prepaid(order, reason="CANCELLED_BY_CLIENT")

        if was_called:
            await self.call_next_if_free(order.barber_id)
        else:
            await self.check_and_send_heads_up_for_barber(order.barber_id)

        await self.audit_repo.log(
            actor_user_id=client_id,
            action="CANCELLED_BY_CLIENT",
            entity="Order",
            entity_id=str(order.id),
        )
        return order

    async def cancel_by_staff(self, order_id: int, staff_user_id: int) -> Order:
        """Cancel order by barber or owner."""
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise QueueException("Order not found")

        await self.barber_repo.lock_barber_for_update(order.barber_id)

        if order.status in [
            OrderStatus.COMPLETED.value,
            OrderStatus.CANCELLED_BY_CLIENT.value,
            OrderStatus.CANCELLED_BY_STAFF.value,
            OrderStatus.CANCELLED_NO_SHOW.value,
            OrderStatus.EXPIRED.value,
        ]:
            return order

        was_called_or_in_service = order.status in [
            OrderStatus.CALLED.value,
            OrderStatus.IN_SERVICE.value,
        ]
        order.status = OrderStatus.CANCELLED_BY_STAFF.value
        order.cancelled_at = now_utc()
        order.deadline_at = None
        await self.session.flush()

        await self._flag_refund_if_prepaid(order, reason="CANCELLED_BY_STAFF")

        if was_called_or_in_service:
            await self.call_next_if_free(order.barber_id)
        else:
            await self.check_and_send_heads_up_for_barber(order.barber_id)

        await self.audit_repo.log(
            actor_user_id=staff_user_id,
            action="CANCELLED_BY_STAFF",
            entity="Order",
            entity_id=str(order.id),
        )
        return order

    async def _flag_refund_if_prepaid(self, order: Order, reason: str = "CANCELLED") -> None:
        """If order had a PAID payment, mark it as REFUND_PENDING, notify owner and inform client."""
        payment = await self.payment_repo.get_by_order_id(order.id)
        if payment and payment.status == PaymentStatus.PAID.value:
            payment.status = PaymentStatus.REFUND_PENDING.value
            payment.refund_reason = reason
            await self.session.flush()
            logger.info("Payment #%s flagged as REFUND_PENDING for Order #%s (%s)", payment.id, order.id, reason)

            amount_fmt = format_money(payment.amount)
            for owner_id in settings.OWNER_TELEGRAM_IDS:
                owner_text = t(
                    "payments.refund_pending_notify_owner",
                    "uz",
                    order_id=order.id,
                    amount=amount_fmt,
                    method=payment.method,
                )
                await self.notifier.send_message(owner_id, owner_text)

            if order.client:
                client_text = t(
                    "payments.refund_pending_notify_client",
                    lang=order.client.language,
                    amount=amount_fmt,
                )
                await self.notifier.send_message(order.client.telegram_id, client_text)
