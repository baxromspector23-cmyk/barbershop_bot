from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    OWNER = "OWNER"
    BARBER = "BARBER"
    CLIENT = "CLIENT"


class OrderStatus(str, enum.Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    WAITING = "WAITING"
    CALLED = "CALLED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED_BY_CLIENT = "CANCELLED_BY_CLIENT"
    CANCELLED_BY_STAFF = "CANCELLED_BY_STAFF"
    CANCELLED_NO_SHOW = "CANCELLED_NO_SHOW"
    EXPIRED = "EXPIRED"


class PaymentMethod(str, enum.Enum):
    PAYME = "PAYME"
    CLICK = "CLICK"
    PAYNET = "PAYNET"
    CASH = "CASH"
    TRANSFER = "TRANSFER"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    RECEIPT_SENT = "RECEIPT_SENT"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class Language(str, enum.Enum):
    UZ = "uz"
    UZ_CYRL = "uz_cyrl"
    RU = "ru"
