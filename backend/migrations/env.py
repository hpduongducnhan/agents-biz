"""Alembic: một chuỗi duy nhất cho toàn app (D3)."""

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel
from sqlmodel.sql.sqltypes import AutoString

import app.models  # noqa: F401 — nạp mọi bảng vào metadata

config = context.config


def render_item(type_, obj, autogen_context):
    """AutoString của SQLModel → sa.String: file migration không phụ thuộc sqlmodel."""
    if type_ == "type" and isinstance(obj, AutoString):
        return f"sa.String(length={obj.length})" if obj.length else "sa.String()"
    return False


engine = create_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=SQLModel.metadata,
        render_item=render_item,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
