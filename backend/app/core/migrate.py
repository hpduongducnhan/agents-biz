"""`bw migrate` / `bw revision`: MỘT chuỗi Alembic cho toàn app (B5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, pool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.connections.postgres import Postgres
from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
SCRIPT_DIR = BACKEND_DIR / "migrations"


def alembic_config(settings: Settings) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(SCRIPT_DIR))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("sqlalchemy.url", settings.POSTGRES_RW_URL.replace("%", "%%"))
    return cfg


def run_migrations(settings: Settings) -> None:
    command.upgrade(alembic_config(settings), "head")
    logger.info("migrate xong: %s", current_revision(settings), extra={"loc": "db0020"})


def current_revision(settings: Settings) -> str | None:
    engine = create_engine(settings.POSTGRES_RW_URL, poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def make_revision(settings: Settings, message: str, *, autogenerate: bool = True) -> Path:
    script = command.revision(alembic_config(settings), message=message, autogenerate=autogenerate)
    return Path(script.path)


PostMigrateStep = Callable[[AsyncSession, Settings], Awaitable[dict | None]]
_STEPS: dict[str, tuple[int, PostMigrateStep]] = {}


def post_migrate_step(name: str, *, order: int = 100) -> Callable[[PostMigrateStep], PostMigrateStep]:
    """Đăng ký một bước chạy sau Alembic ở `bw migrate`; bước phải idempotent. Đăng ký lại cùng tên thì thay bản cũ."""

    def deco(fn: PostMigrateStep) -> PostMigrateStep:
        _STEPS[name] = (order, fn)
        return fn

    return deco


async def run_post_migrate(settings: Settings) -> dict[str, dict | None]:
    """Chạy mọi bước đã đăng ký theo (order, tên), mỗi bước một transaction RW riêng."""
    pg = Postgres(settings)
    out: dict[str, dict | None] = {}
    try:
        for name, (_, step) in sorted(_STEPS.items(), key=lambda item: (item[1][0], item[0])):
            async with pg.rw() as session:
                out[name] = await step(session, settings)
    finally:
        await pg.close()
    logger.info("sau migrate: %s", out, extra={"loc": "db0021"})
    return out
