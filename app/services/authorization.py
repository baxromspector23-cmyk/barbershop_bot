from __future__ import annotations

import logging

from app.models.barber import Barber
from app.models.enums import UserRole
from app.models.order import Order
from app.models.service import Service
from app.models.user import User

logger = logging.getLogger(__name__)


class AuthorizationError(Exception):
    """Raised when an operation is not authorized."""
    pass


def assert_staff(user: User) -> None:
    """Ensure user is BARBER or OWNER."""
    if not user or user.role not in [UserRole.BARBER.value, UserRole.OWNER.value]:
        logger.warning(
            "Unauthorized staff access attempt: user_id=%s, role=%s",
            getattr(user, "id", None),
            getattr(user, "role", None),
        )
        raise AuthorizationError("Only barbers or owners can perform this action.")


def assert_can_manage_order(user: User, order: Order, barber: Barber | None = None) -> None:
    """
    Ensure acting user can manage the given order.
    Acting user must be OWNER or the barber to whom the order belongs.
    """
    assert_staff(user)
    if user.role == UserRole.OWNER.value:
        return

    acting_barber_id = barber.id if barber else getattr(getattr(user, "barber", None), "id", None)
    if acting_barber_id is None:
        logger.warning("Barber profile not found for user %s when managing order %s", user.id, order.id)
        raise AuthorizationError("Barber profili topilmadi")

    if order.barber_id != acting_barber_id:
        logger.warning(
            "Unauthorized cross-barber order attempt: user_id=%s (barber_id=%s) tried to manage order_id=%s (order_barber_id=%s)",
            user.id,
            acting_barber_id,
            order.id,
            order.barber_id,
        )
        raise AuthorizationError("Bu buyurtma sizga tegishli emas")


def assert_can_manage_service(user: User, service: Service, barber: Barber | None = None) -> None:
    """
    Ensure acting user can manage the given service.
    Acting user must be OWNER or the barber to whom the service belongs.
    """
    assert_staff(user)
    if user.role == UserRole.OWNER.value:
        return

    acting_barber_id = barber.id if barber else getattr(getattr(user, "barber", None), "id", None)
    if acting_barber_id is None:
        logger.warning("Barber profile not found for user %s when managing service %s", user.id, service.id)
        raise AuthorizationError("Barber profili topilmadi")

    if service.barber_id != acting_barber_id:
        logger.warning(
            "Unauthorized cross-barber service attempt: user_id=%s (barber_id=%s) tried to manage service_id=%s (service_barber_id=%s)",
            user.id,
            acting_barber_id,
            service.id,
            service.barber_id,
        )
        raise AuthorizationError("Bu xizmat sizga tegishli emas")
