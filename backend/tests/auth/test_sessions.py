"""Phiên: cấp cặp token, xoay vòng refresh theo họ, hai tab refresh cùng lúc, token cũ bị dùng lại, hết hạn,
đồng bộ superadmin theo env ở mỗi lần refresh."""

import asyncio

import pytest
from sqlalchemy import text

from app.auth.sessions import issue_session, revoke_all, rotate_refresh
from app.auth.tokens import get_token_service, hash_token
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from tests.auth.factories import make_user, user_perms

pytestmark = pytest.mark.integration


async def _login(settings, email: str = "s@x.io", **kw):
    async with get_connections().postgres.rw() as s:
        user = await make_user(s, email, **kw)
        pair = await issue_session(s, user, settings=settings, ip="10.0.0.1")
    return user, pair


async def _rotate(settings, raw: str):
    async with get_connections().postgres.rw() as s:
        return await rotate_refresh(s, raw, settings=settings, ip="10.0.0.2")


async def _code(coro) -> int:
    with pytest.raises(AppException) as err:
        await coro
    assert err.value.status_code == 401
    return err.value.code


async def _sql(query: str, **params) -> None:
    async with get_connections().postgres.rw() as s:
        await s.exec(text(query).bindparams(**params))


async def test_issue_and_rotate_keep_the_family(app_env):
    user, pair = await _login(app_env)
    claims = get_token_service().decode_access(pair.access_token)
    assert (claims["sub"], claims["sup"], claims["perms"]) == (str(user.id), False, user_perms())
    assert (pair.expires_in, pair.token_type) == (1800, "bearer")
    _, new = await _rotate(app_env, pair.refresh_token)
    assert new.refresh_token != pair.refresh_token
    async with get_connections().postgres.ro() as s:
        q = "select token_hash, family_id, revoked_at is not null, ip from refresh_tokens order by created_at"
        rows = (await s.exec(text(q))).all()
    assert [r[0] for r in rows] == [hash_token(pair.refresh_token), hash_token(new.refresh_token)]
    assert rows[0][1] == rows[1][1] and [r[2] for r in rows] == [True, False] and rows[1][3] == "10.0.0.2"


async def test_two_tabs_refreshing_at_once_keep_the_session(app_env):
    _, pair = await _login(app_env)
    results = await asyncio.gather(
        _rotate(app_env, pair.refresh_token), _rotate(app_env, pair.refresh_token), return_exceptions=True
    )
    wins = [r for r in results if not isinstance(r, BaseException)]
    losses = [r for r in results if isinstance(r, AppException)]
    assert len(wins) == 1 and [e.code for e in losses] == [2104]
    await _rotate(app_env, wins[0][1].refresh_token)  # họ còn sống: tab thắng dùng tiếp được


async def test_reuse_after_grace_revokes_whole_family(app_env):
    _, pair = await _login(app_env)
    _, legit = await _rotate(app_env, pair.refresh_token)
    await _sql(
        "update refresh_tokens set revoked_at = now() - interval '1 minute' where token_hash = :h",
        h=hash_token(pair.refresh_token),
    )
    assert await _code(_rotate(app_env, pair.refresh_token)) == 2104
    assert await _code(_rotate(app_env, legit.refresh_token)) == 2104  # cả họ bị thu hồi — chủ thật cũng đăng nhập lại


async def test_reuse_after_logout_is_rejected_even_inside_grace(app_env):
    user, pair = await _login(app_env)
    async with get_connections().postgres.rw() as s:
        await revoke_all(s, user.id)
    assert await _code(_rotate(app_env, pair.refresh_token)) == 2104


async def test_unknown_expired_and_disabled_are_2104(app_env):
    assert await _code(_rotate(app_env, "không-có-token-này")) == 2104
    user, pair = await _login(app_env, "exp@x.io")
    await _sql("update refresh_tokens set expires_at = now() - interval '1 second' where user_id = :u", u=user.id)
    assert await _code(_rotate(app_env, pair.refresh_token)) == 2104
    off, pair2 = await _login(app_env, "off@x.io")
    await _sql("update users set is_active = false where id = :u", u=off.id)
    assert await _code(_rotate(app_env, pair2.refresh_token)) == 2104


async def test_refresh_follows_superadmin_env(app_env, monkeypatch):
    root, pair = await _login(app_env, "root@test.local")
    assert get_token_service().decode_access(pair.access_token)["sup"] is False  # make_user không đọc env
    user, up = await _rotate(app_env, pair.refresh_token)
    assert user.is_superadmin and get_token_service().decode_access(up.access_token)["sup"] is True
    monkeypatch.setattr(app_env, "SUPERADMIN_EMAILS", "")  # deploy mới bỏ email này khỏi env
    user, down = await _rotate(app_env, up.refresh_token)
    claims = get_token_service().decode_access(down.access_token)
    assert not user.is_superadmin and claims["sup"] is False and claims["perms"] == user_perms()
    async with get_connections().postgres.ro() as s:
        flag = (await s.exec(text("select is_superadmin from users where id = :u").bindparams(u=root.id))).one()[0]
    assert flag is False
