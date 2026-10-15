"""Principal (không org): quyền hệ thống + cờ superadmin; resolver cắm từ miền auth; claims → Principal;
dấu tài khoản bị khoá trong Redis."""

import uuid
from dataclasses import FrozenInstanceError

import pytest
from fastapi import Depends, FastAPI, Request

from app.core.errors import AppException
from app.core.exception_handlers import register_exception_handlers
from app.core.security import principal as principal_mod
from app.core.security.principal import (
    Principal,
    disabled_key,
    is_disabled,
    principal_from_claims,
    require_principal,
    resolve_principal,
    set_principal_resolver,
)
from tests.conftest import asgi_client

U1 = uuid.UUID("00000000-0000-4000-8000-000000000001")


def test_can_checks_perm_and_superadmin():
    p = Principal(user_id=U1, perms=frozenset({"user.view"}))
    assert p.can(None) and p.can("user.view") and not p.can("user.manage")
    assert Principal(user_id=U1, sup=True).can("user.manage")


def test_principal_is_frozen():
    with pytest.raises(FrozenInstanceError):
        Principal(user_id=U1).sup = True  # type: ignore[misc]


@pytest.fixture
def app():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/me")
    async def me(request: Request, p: Principal = Depends(require_principal)):
        return {"user": str(p.user_id), "state_user": request.state.user_id}

    @app.get("/maybe")
    async def maybe(request: Request):
        return {"anon": await resolve_principal(request) is None}

    yield app
    set_principal_resolver(None)


async def test_no_resolver_is_401_and_anonymous(app):
    set_principal_resolver(None)
    async with asgi_client(app) as c:
        r = await c.get("/me")
        anon = await c.get("/maybe")
    assert r.status_code == 401 and r.json()["code"] == 1004
    assert anon.json() == {"anon": True}


async def test_missing_resolver_fallback_is_logged_once(app, monkeypatch, bw_log):
    monkeypatch.setitem(principal_mod._state, "warned", False)
    set_principal_resolver(None)
    async with asgi_client(app) as c:
        await c.get("/maybe")
        await c.get("/maybe")
    lines = [line for line in bw_log() if line["loc"] == "sys0406"]
    assert len(lines) == 1 and "DEFAULTS_APPLIED=[principal_resolver=none]" in lines[0]["msg"]  # R11


async def test_resolver_result_is_used_and_written_to_state(app):
    async def resolver(request):
        return Principal(user_id=U1)

    set_principal_resolver(resolver)
    async with asgi_client(app) as c:
        r = await c.get("/me")
    assert r.json() == {"user": str(U1), "state_user": str(U1)}


async def test_resolver_error_propagates(app):
    async def resolver(request):
        raise AppException(2104, status_code=401)

    set_principal_resolver(resolver)
    async with asgi_client(app) as c:
        r = await c.get("/me")
    assert r.status_code == 401 and r.json()["code"] == 2104


def test_principal_from_claims():
    p = principal_from_claims({"sub": str(U1), "perms": ["user.view"], "sup": False})
    assert p == Principal(user_id=U1, perms=frozenset({"user.view"}), sup=False)
    assert principal_from_claims({"sub": str(U1), "perms": ["x"], "sup": True}).perms == frozenset()
    assert principal_from_claims({"sub": "khong-phai-uuid"}) is None
    assert principal_from_claims({}) is None


async def test_disabled_key_and_check():
    class FakeRedis:
        def __init__(self, keys):
            self.keys = keys

        async def exists(self, key):
            return int(key in self.keys)

    assert disabled_key(U1) == f"bw:auth:disabled:{U1}"
    assert await is_disabled(FakeRedis({f"bw:auth:disabled:{U1}"}), U1) is True
    assert await is_disabled(FakeRedis(set()), U1) is False
