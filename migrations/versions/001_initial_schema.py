"""initial_schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="uz"),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="CLIENT"),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("bot_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    # 2. barbers
    op.create_table(
        "barbers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("photo_file_id", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    # 3. barber_working_hours
    op.create_table(
        "barber_working_hours",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("barber_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_day_off", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["barber_id"], ["barbers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bwh_barber_id", "barber_working_hours", ["barber_id"])

    # 4. services
    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("barber_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["barber_id"], ["barbers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_services_barber_id", "services", ["barber_id"])

    # 5. orders
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("barber_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("walkin_name", sa.String(length=255), nullable=True),
        sa.Column("walkin_phone", sa.String(length=50), nullable=True),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("service_name", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="WAITING"),
        sa.Column("position_key", sa.BigInteger(), nullable=False),
        sa.Column("ticket_no", sa.Integer(), nullable=False),
        sa.Column("ticket_date", sa.Date(), nullable=False),
        sa.Column("late_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heads_up_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["barber_id"], ["barbers.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_active_client_order",
        "orders",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("client_id IS NOT NULL AND status IN ('WAITING', 'CALLED', 'IN_SERVICE', 'PENDING_PAYMENT')"),
    )
    op.create_index(
        "ix_barber_status_position",
        "orders",
        ["barber_id", "status", "position_key"],
    )
    op.create_index(
        "ix_called_deadline",
        "orders",
        ["deadline_at"],
        postgresql_where=sa.text("status = 'CALLED'"),
    )

    # 6. payments
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("barber_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True),
        sa.ForeignKeyConstraint(["barber_id"], ["barbers.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("method", "provider_payment_id", name="uq_payment_method_provider_id"),
    )
    op.create_index("ix_payment_revenue", "payments", ["status", "paid_at"])

    # 7. barber_invites
    op.create_table(
        "barber_invites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_barber_invites_token_hash", "barber_invites", ["token_hash"], unique=True)

    # 8. audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column("data", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # 9. processed_updates
    op.create_table(
        "processed_updates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processed_updates_update_id", "processed_updates", ["update_id"], unique=True)


def downgrade() -> None:
    op.drop_table("processed_updates")
    op.drop_table("audit_log")
    op.drop_table("barber_invites")
    op.drop_table("payments")
    op.drop_table("orders")
    op.drop_table("services")
    op.drop_table("barber_working_hours")
    op.drop_table("barbers")
    op.drop_table("users")
