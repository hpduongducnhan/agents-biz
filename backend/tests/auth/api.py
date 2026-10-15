"""Helper gọi API thật qua ASGI cho test. Đường dẫn theo quy ước operation: op đọc → GET /<miền>/<việc>?query,
op ghi → POST /<miền>/<việc> + JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx2

from app.core.connections.registry import get_connections
from app.system.settings_store import SystemSettings
from tests.auth.factories import PASSWORD, make_user

P = "/bizwithagents/api"
TOKEN_KEYS = ("access_token", "refresh_token", "token_type", "expires_in")


def op_path(op: str) -> str:
    """`admin.list_users` → `/admin/list_users`; `auth.google.authorize` → `/auth/google/authorize`."""
    return "/" + op.replace(".", "/")


@dataclass
class Session:
    user: dict
    tokens: dict
    email: str
    password: str = PASSWORD
    verification_sent: bool = False

    @property
    def id(self) -> str:
        return self.user["id"]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens['access_token']}"}


class Api:
    def __init__(self, client: httpx2.AsyncClient) -> None:
        self.c = client

    async def call(self, method: str, path: str, who: Session | None = None, **kw) -> httpx2.Response:
        headers = kw.pop("headers", {}) | (who.headers if who else {})
        return await self.c.request(method, f"{P}{path}", headers=headers, **kw)

    async def ok(self, method: str, path: str, who: Session | None = None, **kw) -> Any:
        r = await self.call(method, path, who, **kw)
        assert r.status_code == 200, r.text
        return r.json()["data"]

    async def get(self, op: str, who: Session | None = None, **params) -> Any:
        """Op đọc; tham số None bị bỏ."""
        return await self.ok("GET", op_path(op), who, params={k: v for k, v in params.items() if v is not None})

    async def post(self, op: str, who: Session | None = None, **body) -> Any:
        return await self.ok("POST", op_path(op), who, json=body)

    async def err(self, method: str, op: str, who: Session | None = None, **kw) -> tuple[int, int | None]:
        """Gọi op mong lỗi → (HTTP status, mã lỗi). Body: `json=…`; query: `params=…`."""
        r = await self.call(method, op_path(op), who, **kw)
        return r.status_code, r.json().get("code")

    async def register(self, email: str, password: str = PASSWORD, name: str = "", **extra) -> Session:
        data = await self.post("auth.register", email=email, password=password, name=name, **extra)
        return Session(data["user"], data["tokens"], data["user"]["email"], password, data["verification_sent"])

    async def login(self, email: str, password: str = PASSWORD) -> Session:
        data = await self.post("auth.login", email=email, password=password)
        return Session(data["user"], data["tokens"], data["user"]["email"], password)

    async def refresh(self, who: Session) -> Session:
        """Lấy token mới (quyền mới nhất) — như FE làm khi nhận core:rbac_updated."""
        tokens = await self.post("auth.refresh", refresh_token=who.tokens["refresh_token"])
        me = await self.ok("GET", "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        return Session(me, tokens, who.email, who.password)

    async def as_user(self, email: str, *, roles=("member",), password: str = PASSWORD, **kw) -> Session:
        """Tạo user thẳng DB rồi đăng nhập. Superadmin: dùng root@test.local (có trong SUPERADMIN_EMAILS)."""
        async with get_connections().postgres.rw() as s:
            await make_user(s, email, roles=roles, password=password, **kw)
        return await self.login(email, password)


def events_to(hub, key: str) -> list[str]:
    """Tên event realtime đã gửi tới routing key `key` (hub = RecordingHub)."""
    return [event for routing_key, event, _ in hub.events() if routing_key == key]


def data_of(hub, key: str, event: str) -> list[dict]:
    return [data for routing_key, ev, data in hub.events() if routing_key == key and ev == event]


def system_flags(**overrides):
    """Thay cài đặt hệ thống trong test (mọi khoá khác giữ mặc định):
    `monkeypatch.setattr(settings_store, "get_system_settings", system_flags(signup_mode="invite_only"))`."""
    values = SystemSettings.model_validate({"google_enabled": False} | overrides)

    async def fake(session):
        return values

    return fake
