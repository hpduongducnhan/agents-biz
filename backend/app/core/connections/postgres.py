"""Postgres — 2 engine RW / RO trên cùng driver psycopg3; session RO là READ ONLY."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import wraps
from typing import TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger(__name__)
_AFTER_COMMIT = "bw_after_commit"
F = TypeVar("F", bound=Callable[..., Awaitable])


def after_commit(session: AsyncSession, hook: Callable[[], Awaitable[None]]) -> None:
    """Chạy `hook()` đúng 1 lần SAU khi UoW RW commit; rollback thì bỏ."""
    session.info.setdefault(_AFTER_COMMIT, []).append(hook)


async def _run_after_commit(hooks) -> None:
    for hook in hooks:
        try:
            await hook()
        except Exception as exc:  # noqa: BLE001 — transaction đã bền; hook hỏng chỉ được báo, không được ném
            logger.warning(
                "after-commit hook lỗi %s: %s", getattr(hook, "__qualname__", hook), exc, extra={"loc": "db0003"}
            )


class Postgres:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self.rw_engine = self._engine(settings.POSTGRES_RW_URL, settings.POSTGRES_POOL_SIZE)
        self.ro_engine = self._engine(settings.postgres_ro_url, settings.postgres_ro_pool_size)
        self._rw_sessions = async_sessionmaker(self.rw_engine, class_=AsyncSession, expire_on_commit=False)
        self._ro_sessions = async_sessionmaker(self.ro_engine, class_=AsyncSession, expire_on_commit=False)
        self._raw: dict[str, AsyncConnectionPool] = {}
        self._raw_lock = asyncio.Lock()

    def _engine(self, url: str, pool_size: int) -> AsyncEngine:
        connect_args: dict = {}
        if self._s.POSTGRES_PGBOUNCER:
            connect_args["prepare_threshold"] = None
        if self._s.POSTGRES_STATEMENT_TIMEOUT > 0:
            connect_args["options"] = f"-c statement_timeout={self._s.POSTGRES_STATEMENT_TIMEOUT * 1000}"
        return create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=self._s.POSTGRES_MAX_OVERFLOW,
            pool_pre_ping=self._s.POSTGRES_POOL_PRE_PING,
            pool_recycle=self._s.POSTGRES_POOL_RECYCLE,
            connect_args=connect_args,
        )

    @asynccontextmanager
    async def rw(self, *, read_only: bool = False) -> AsyncIterator[AsyncSession]:
        """UoW trên kênh RW; `read_only` → transaction READ ONLY (đọc ngay sau ghi mà không được ghi)."""
        session = self._rw_sessions()
        committed = False
        try:
            if read_only:
                await session.exec(text("SET TRANSACTION READ ONLY"))
            yield session
            await session.commit()
            committed = True
        except BaseException:
            try:
                await session.rollback()
            except Exception as exc:  # noqa: BLE001 — lỗi gốc mới là thứ cần ném; rollback hỏng chỉ được báo
                logger.warning("rollback lỗi: %s", exc, extra={"loc": "db0005"})
            raise
        finally:
            hooks = session.info.pop(_AFTER_COMMIT, ())
            await session.close()
            if committed:
                await _run_after_commit(hooks)

    @asynccontextmanager
    async def ro(self) -> AsyncIterator[AsyncSession]:
        session = self._ro_sessions()
        try:
            await session.exec(text("SET TRANSACTION READ ONLY"))
            yield session
        finally:
            await session.close()

    async def ping(self, channel: str) -> None:
        async with self.rw() if channel == "rw" else self.ro() as session:
            await session.exec(text("SELECT 1"))

    async def raw_pool(
        self, key: str, *, search_path: str | None = None, dict_rows: bool = False, max_size: int = 5
    ) -> AsyncConnectionPool:
        """Pool psycopg thô trên kênh RW (autocommit) cho thư viện cần kết nối psycopg riêng — mở lười theo `key`,
        đóng cùng các engine."""
        if key in self._raw:
            return self._raw[key]
        async with self._raw_lock:
            if key not in self._raw:
                options = []
                if search_path:
                    options.append(f"-c search_path={search_path}")
                if self._s.POSTGRES_STATEMENT_TIMEOUT > 0:
                    options.append(f"-c statement_timeout={self._s.POSTGRES_STATEMENT_TIMEOUT * 1000}")
                kwargs: dict = {"autocommit": True, "prepare_threshold": None if self._s.POSTGRES_PGBOUNCER else 0}
                if options:
                    kwargs["options"] = " ".join(options)
                if dict_rows:
                    kwargs["row_factory"] = dict_row
                pool = AsyncConnectionPool(
                    conninfo=self._s.POSTGRES_RW_URL.replace("postgresql+psycopg://", "postgresql://", 1),
                    min_size=1,
                    max_size=max_size,
                    open=False,
                    kwargs=kwargs,
                )
                await pool.open()
                self._raw[key] = pool
        return self._raw[key]

    async def close(self) -> None:
        await self.rw_engine.dispose()
        await self.ro_engine.dispose()
        for pool in self._raw.values():
            await pool.close()
        self._raw.clear()


def is_disconnect_error(exc: BaseException) -> bool:
    if getattr(exc, "connection_invalidated", False):
        return True
    orig = getattr(exc, "orig", None)
    return any(isinstance(c, psycopg.OperationalError) for c in (exc, orig, getattr(orig, "__cause__", None)))


def retry_on_disconnect(max_retries: int) -> Callable[[F], F]:
    """Thử lại một hàm TỰ MỞ `rw()` bên trong khi mất kết nối giữa chừng (rollback đã sạch)."""

    def deco(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_retries or not is_disconnect_error(exc):
                        raise
                    logger.warning(
                        "mất kết nối DB, thử lại %d/%d %s: %s",
                        attempt + 1,
                        max_retries,
                        func.__qualname__,
                        exc,
                        extra={"loc": "db0004"},
                    )
                    await asyncio.sleep(0.1 * (attempt + 1))
            raise RuntimeError("retry_on_disconnect: vòng lặp kết thúc bất thường")

        return wrapper  # type: ignore[return-value]

    return deco
