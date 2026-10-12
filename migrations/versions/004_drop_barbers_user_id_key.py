"""drop redundant barbers_user_id_key constraint

Revision ID: 004_drop_barbers_user_id_key
Revises: 003_schema_indexes_and_parity
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "004_drop_barbers_user_id_key"
down_revision: Union[str, None] = "003_schema_indexes_and_parity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("barbers_user_id_key", "barbers", type_="unique")
    elif bind.dialect.name != "sqlite":
        with op.batch_alter_table("barbers") as batch_op:
            batch_op.drop_constraint("barbers_user_id_key", type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_unique_constraint("barbers_user_id_key", "barbers", ["user_id"])
    elif bind.dialect.name != "sqlite":
        with op.batch_alter_table("barbers") as batch_op:
            batch_op.create_unique_constraint("barbers_user_id_key", ["user_id"])
