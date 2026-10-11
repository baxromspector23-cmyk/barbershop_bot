"""schema_indexes_and_parity

Revision ID: 003_schema_indexes_and_parity
Revises: 002_refund_and_stale
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_schema_indexes_and_parity"
down_revision: Union[str, None] = "002_refund_and_stale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Audit log index
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])

    # 2. Barber working hours index rename
    op.drop_index("ix_bwh_barber_id", table_name="barber_working_hours")
    op.create_index("ix_barber_working_hours_barber_id", "barber_working_hours", ["barber_id"])

    # 3. Barbers user_id unique index
    op.create_index("ix_barbers_user_id", "barbers", ["user_id"], unique=True)

    # 4. Orders indexes
    op.create_index("ix_orders_barber_id", "orders", ["barber_id"])
    op.create_index("ix_orders_client_id", "orders", ["client_id"])
    op.create_index("ix_orders_position_key", "orders", ["position_key"])
    op.create_index("ix_orders_status", "orders", ["status"])

    # 5. Payments indexes
    op.create_index("ix_payments_barber_id", "payments", ["barber_id"])
    op.create_index("ix_payments_client_id", "payments", ["client_id"])
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_paid_at", "payments", ["paid_at"])
    op.create_index("ix_payments_status", "payments", ["status"])

    # 6. Partial unique index: at most one PAID payment per order
    op.create_index(
        "uq_one_paid_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PAID'"),
        sqlite_where=sa.text("status = 'PAID'"),
    )


def downgrade() -> None:
    op.drop_index("uq_one_paid_per_order", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_paid_at", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_index("ix_payments_client_id", table_name="payments")
    op.drop_index("ix_payments_barber_id", table_name="payments")

    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_position_key", table_name="orders")
    op.drop_index("ix_orders_client_id", table_name="orders")
    op.drop_index("ix_orders_barber_id", table_name="orders")

    op.drop_index("ix_barbers_user_id", table_name="barbers")

    op.drop_index("ix_barber_working_hours_barber_id", table_name="barber_working_hours")
    op.create_index("ix_bwh_barber_id", "barber_working_hours", ["barber_id"])

    op.drop_index("ix_audit_log_actor_user_id", table_name="audit_log")
