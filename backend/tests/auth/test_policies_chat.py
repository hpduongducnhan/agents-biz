"""Hạn mức chat: `effective_limits` — một lượt nhiều khoá, `zero_unlimited` (0 thắng mọi số khi gộp role)."""

import pytest

from app.auth.models import User
from app.auth.policies import CHAT_KEYS, effective_limits
from app.core.connections.registry import get_connections
from tests.auth.factories import make_role, make_user

pytestmark = pytest.mark.integration
DEFAULTS = {"chat_per_minute": 10, "chat_per_hour": 100, "chat_per_day": 400}


async def role_policies(session, name: str, policies: dict) -> None:
    role = await make_role(session, name, [])
    role.policies = policies
    session.add(role)
    await session.flush()


async def eff(email: str, *, roles=("member",), policies=None, superadmin=False, zero=True):
    async with get_connections().postgres.rw() as s:
        user = await make_user(s, email, roles=roles, is_superadmin=superadmin)
        if policies is not None:
            user.policies = policies
            s.add(user)
            await s.flush()
        return await effective_limits(s, await s.get(User, user.id), DEFAULTS, zero_unlimited=zero)


async def test_defaults_when_nothing_set(app_env, rt):
    out = await eff("a@x.io")
    assert {k: (v.value, v.source) for k, v in out.items()} == {k: (DEFAULTS[k], "default") for k in CHAT_KEYS}


async def test_one_role_overrides_default(app_env, rt):
    async with get_connections().postgres.rw() as s:
        await role_policies(s, "r1", {"chat_per_minute": 3})
    out = await eff("a@x.io", roles=("r1",))
    assert (out["chat_per_minute"].value, out["chat_per_minute"].source, out["chat_per_minute"].role) == (
        3,
        "role",
        "r1",
    )
    assert out["chat_per_hour"].source == "default"


async def test_two_roles_take_max(app_env, rt):
    async with get_connections().postgres.rw() as s:
        await role_policies(s, "r1", {"chat_per_minute": 3})
        await role_policies(s, "r2", {"chat_per_minute": 7})
    out = await eff("a@x.io", roles=("r1", "r2"))
    assert (out["chat_per_minute"].value, out["chat_per_minute"].role) == (7, "r2")


async def test_zero_beats_any_number_only_when_zero_unlimited(app_env, rt):
    async with get_connections().postgres.rw() as s:
        await role_policies(s, "r0", {"chat_per_minute": 0})
        await role_policies(s, "r50", {"chat_per_minute": 50})
    out = await eff("a@x.io", roles=("r0", "r50"))
    assert (out["chat_per_minute"].value, out["chat_per_minute"].role) == (0, "r0")
    out = await eff("b@x.io", roles=("r0", "r50"), zero=False)
    assert (out["chat_per_minute"].value, out["chat_per_minute"].role) == (50, "r50")


async def test_user_override_wins_even_lower_than_role(app_env, rt):
    async with get_connections().postgres.rw() as s:
        await role_policies(s, "r1", {"chat_per_minute": 30})
    out = await eff("a@x.io", roles=("r1",), policies={"chat_per_minute": 2})
    assert (out["chat_per_minute"].value, out["chat_per_minute"].source) == (2, "user")


async def test_superadmin_is_unlimited(app_env, rt):
    out = await eff("root@test.local", superadmin=True)
    assert all(v.value is None and v.source == "superadmin" for v in out.values())
