"""refund_reason_and_stale_alerted_at

Revision ID: 002_refund_and_stale
Revises: 001_initial_schema
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_refund_and_stale"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("refund_reason", sa.String(length=50), nullable=True))
    op.add_column("orders", sa.Column("stale_alerted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "stale_alerted_at")
    op.drop_column("payments", "refund_reason")
