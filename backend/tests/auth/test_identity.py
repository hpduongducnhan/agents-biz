"""Resolver JWT: Bearer → Principal; dấu khoá chặn token còn hạn (2103); token superadmin cấp trước khi api khởi
động lại được kiểm lại với DB (đã bị bỏ khỏi SUPERADMIN_EMAILS → 1004 để FE refresh)."""

import time
import uuid

import jwt
import pytest
from starlette.requests import Request

from app.auth import identity
from app.auth.identity import jwt_resolver, mark_disabled
from app.auth.superadmins import sync_superadmins
from app.auth.tokens import get_token_service
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.security.principal import Principal, disabled_key
from tests.auth.factories import make_user

pytestmark = pytest.mark.integration


def _req(token: str | None, scheme: str = "Bearer") -> Request:
    headers = [(b"authorization", f"{scheme} {token}".encode())] if token else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""})


async def _fails(token: str) -> tuple[int, int]:
    with pytest.raises(AppException) as err:
        await jwt_resolver(_req(token))
    return err.value.code, err.value.status_code


async def test_bearer_token_becomes_principal(app_env):
    uid = uuid.uuid4()
    token, _ = get_token_service().issue_access(user_id=uid, sup=False, perms={"user.view"})
    assert await jwt_resolver(_req(token)) == Principal(user_id=uid, perms=frozenset({"user.view"}), sup=False)
    assert await jwt_resolver(_req(None)) is None
    assert await jwt_resolver(_req(token, scheme="Basic")) is None


async def test_bad_tokens_are_1004(app_env):
    svc = get_token_service()
    now = int(time.time())
    claims = {"sub": "không-phải-uuid", "typ": "access", "perms": [], "sup": False, "iat": now, "exp": now + 60}
    assert await _fails("x.y.z") == (1004, 401)
    assert await _fails(jwt.encode(claims, svc.private_key, algorithm="EdDSA")) == (1004, 401)


async def test_disabled_mark_blocks_live_token_at_once(app_env):
    uid = uuid.uuid4()
    token, _ = get_token_service().issue_access(user_id=uid, sup=False, perms=())
    redis = get_connections().redis.rw
    await mark_disabled(redis, uid, True, 1800)
    assert disabled_key(uid) == f"bw:auth:disabled:{uid}"  # đúng khoá mà @on_ws đọc
    assert 0 < await redis.ttl(disabled_key(uid)) <= 1800
    assert await _fails(token) == (2103, 403)
    await mark_disabled(redis, uid, False, 1800)
    assert (await jwt_resolver(_req(token))).user_id == uid


async def test_superadmin_token_from_before_restart_is_rechecked(app_env, monkeypatch):
    async with get_connections().postgres.rw() as s:
        root = await make_user(s, "root@test.local", is_superadmin=True)
        gone = await make_user(s, "gone@x.io", is_superadmin=True)
    svc = get_token_service()
    root_token, _ = svc.issue_access(user_id=root.id, sup=True, perms=())
    gone_token, _ = svc.issue_access(user_id=gone.id, sup=True, perms=())
    assert (await jwt_resolver(_req(gone_token))).sup is True  # token cấp sau lúc process khởi động: tin token
    async with get_connections().postgres.rw() as s:
        await sync_superadmins(s, app_env)  # deploy mới: env chỉ còn root@test.local → migrate gỡ cờ gone@x.io
    monkeypatch.setattr(identity, "BOOT_TS", int(time.time()) + 5)  # …rồi api khởi động lại
    assert (await jwt_resolver(_req(root_token))).sup is True
    assert await _fails(gone_token) == (1004, 401)
