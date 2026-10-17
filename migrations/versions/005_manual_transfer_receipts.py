"""manual card-transfer payments: receipt photo columns

Revision ID: 005_manual_transfer_receipts
Revises: 004_drop_barbers_user_id_key
Create Date: 2026-10-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_manual_transfer_receipts"
down_revision: Union[str, None] = "004_drop_barbers_user_id_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("receipt_file_id", sa.String(length=255), nullable=True))
    op.add_column("payments", sa.Column("receipt_file_unique_id", sa.String(length=255), nullable=True))
    op.add_column("payments", sa.Column("receipt_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True))
    op.create_index(
        "uq_payment_receipt_unique",
        "payments",
        ["receipt_file_unique_id"],
        unique=True,
        postgresql_where=sa.text("receipt_file_unique_id IS NOT NULL"),
        sqlite_where=sa.text("receipt_file_unique_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_payment_receipt_unique", table_name="payments")
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_column("confirmed_by_user_id")
        batch_op.drop_column("receipt_sent_at")
        batch_op.drop_column("receipt_file_unique_id")
        batch_op.drop_column("receipt_file_id")
