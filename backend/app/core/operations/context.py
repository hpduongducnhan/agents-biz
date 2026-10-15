"""OpContext — thứ handler nhận: danh tính, session đúng kênh theo effect, Redis / Mongo, và các cách báo ra ngoài.
Mọi thứ báo ra ngoài (realtime, data:changed, thông báo, hook) đều XẾP HÀNG — runner gửi sau commit."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.connections.mongo import Mongo
from app.core.connections.redis import Redis
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.messaging.realtime import check_out_event
from app.core.operations.spec import Source
from app.core.security.principal import Principal
from app.core.settings import Settings
from app.core.tenancy import scope_session, session_tenant

logger = get_logger(__name__)


@dataclass(frozen=True)
class PendingNotification:
    user_id: uuid.UUID
    kind: str
    title: str
    body: str = ""
    params: dict | None = None
    action: dict | None = None


@dataclass(frozen=True)
class PendingEmit:
    target: str  # "users" | "sup" | "tenant"
    user_ids: tuple[uuid.UUID, ...]
    event: str
    data: dict
    tenant_id: uuid.UUID | None = None


@dataclass
class OpContext:
    principal: Principal | None
    settings: Settings
    session: AsyncSession
    redis: Redis
    mongo: Mongo | None
    cid: str
    source: Source
    agent_run_id: uuid.UUID | None = None
    request_ip: str | None = None
    pending_emits: list[PendingEmit] = field(default_factory=list, init=False, repr=False)
    pending_invalidations: list[tuple[tuple[str, ...], tuple[uuid.UUID, ...]]] = field(
        default_factory=list, init=False, repr=False
    )
    pending_tenant_invalidations: list[tuple[tuple[str, ...], uuid.UUID]] = field(
        default_factory=list, init=False, repr=False
    )
    pending_notifications: list[PendingNotification] = field(default_factory=list, init=False, repr=False)
    pending_hooks: list[Callable[[], Awaitable[None]]] = field(default_factory=list, init=False, repr=False)

    def emit_to_user(self, user_id: uuid.UUID, event: str, data: dict) -> None:
        self.pending_emits.append(PendingEmit("users", (user_id,), check_out_event(event), data))

    def emit_to_users(self, user_ids: Iterable[uuid.UUID], event: str, data: dict) -> None:
        self.pending_emits.append(PendingEmit("users", tuple(user_ids), check_out_event(event), data))

    def emit_to_superadmins(self, event: str, data: dict) -> None:
        self.pending_emits.append(PendingEmit("sup", (), check_out_event(event), data))

    @property
    def tenant_id(self) -> uuid.UUID | None:
        """Tenant của người gọi — session của op đã được lọc theo tenant này (D11)."""
        return self.principal.tenant_id if self.principal is not None else None

    def emit_to_tenant(self, event: str, data: dict) -> None:
        """Sự kiện tới mọi socket của tenant người gọi (D13) — chỉ cho tín hiệu không lộ dữ liệu."""
        if self.tenant_id is not None:
            self.pending_emits.append(PendingEmit("tenant", (), check_out_event(event), data, self.tenant_id))

    def invalidate(self, keys: Iterable[str], users: Iterable[uuid.UUID] = (), *, tenant: bool = False) -> None:
        """`data:changed {keys}` sau commit tới `users` và / hoặc cả tenant người gọi (`tenant=True`) — ngoài
        `spec.invalidates` gửi cho người gọi."""
        users = tuple(users)
        if users:
            self.pending_invalidations.append((tuple(keys), users))
        if tenant and self.tenant_id is not None:
            self.pending_tenant_invalidations.append((tuple(keys), self.tenant_id))

    @contextmanager
    def cross_tenant(self) -> Iterator[AsyncSession]:
        """Bỏ lọc tenant trong khối `with` — chỉ superadmin (màn quản trị nền tảng). Ghi log `sys0601`."""
        if self.principal is None or not self.principal.sup:
            raise AppException(1005, status_code=403, detail="Chỉ superadmin")
        logger.info("xem chéo tenant user=%s", self.principal.user_id, extra={"loc": "sys0601"})
        previous = session_tenant(self.session)
        scope_session(self.session, None)
        try:
            yield self.session
        finally:
            scope_session(self.session, previous)

    def notify(
        self,
        user_id: uuid.UUID,
        kind: str,
        title: str,
        body: str = "",
        params: dict | None = None,
        action: dict | None = None,
    ) -> None:
        self.pending_notifications.append(PendingNotification(user_id, kind, title, body, params, action))

    def after_commit(self, hook: Callable[[], Awaitable[None]]) -> None:
        self.pending_hooks.append(hook)
