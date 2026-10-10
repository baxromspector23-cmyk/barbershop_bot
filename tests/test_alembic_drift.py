import os
import tempfile

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db.base import Base


def test_alembic_upgrade_to_head_and_schema_drift():
    """Q1: Verify Alembic migrations run cleanly and generate all declared tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        tmp_db_path = tmp_db.name

    try:
        db_url = f"sqlite:///{tmp_db_path}"
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        os.environ["DATABASE_URL"] = db_url

        # 1. Run migrations upgrade head
        command.upgrade(alembic_cfg, "head")

        # 2. Inspect generated database schema
        engine = create_engine(db_url)
        inspector = inspect(engine)
        migrated_tables = set(inspector.get_table_names())

        # Exclude alembic_version from model check
        migrated_tables.discard("alembic_version")

        # 3. Verify all tables in Base.metadata exist in the migrated database
        model_tables = set(Base.metadata.tables.keys())
        missing_tables = model_tables - migrated_tables

        assert not missing_tables, f"Tables missing after Alembic migration: {missing_tables}"

        # 4. Verify columns in each table
        for table_name in model_tables:
            migrated_cols = {col["name"] for col in inspector.get_columns(table_name)}
            model_cols = {col.name for col in Base.metadata.tables[table_name].columns}
            missing_cols = model_cols - migrated_cols
            assert not missing_cols, f"Columns missing in {table_name} after migration: {missing_cols}"
    finally:
        if os.path.exists(tmp_db_path):
            try:
                os.remove(tmp_db_path)
            except OSError:
                pass
