"""Khối `<context>`: người dùng, giờ, quyền trợ lý + provider do module đăng ký (thứ tự, trần dòng, lỗi không lan)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.agent.runtime import context
from app.core.connections.registry import get_connections
from tests.auth.factories import make_role, make_user

NOW = datetime(2026, 10, 12, 3, 30, tzinfo=UTC)  # 10:30 giờ Việt Nam, thứ Hai


async def build(user_id: str, **kw) -> str:
    async with get_connections().postgres.ro() as s:
        return await context.build(s, uuid.UUID(user_id), now=NOW, **kw)


async def short(user_id: str) -> str:
    async with get_connections().postgres.ro() as s:
        return await context.short(s, uuid.UUID(user_id))


@pytest.fixture(autouse=True)
def clean_providers():
    before = dict(context._PROVIDERS)
    yield
    context._PROVIDERS.clear()
    context._PROVIDERS.update(before)


def lines_fn(*lines):
    async def fn(session, user):
        return list(lines)

    return fn


async def test_context_header_and_extra_lines(api):
    u = await api.as_user("ctx@x.io")
    text = await build(u.id, extra=["hook: nhớ nói lời cảm ơn"])
    lines = text.splitlines()
    assert lines[0] == "<context>" and lines[-1] == "</context>" and lines[-2] == "hook: nhớ nói lời cảm ơn"
    assert f"user: {u.id} · ctx · múi giờ Asia/Ho_Chi_Minh · ngôn ngữ vi · role member" in text
    assert "now: 2026-10-12T10:30+07:00 (Monday)" in text and "agent_access" not in text
    assert await build(str(uuid.uuid4())) == ""
    root = await api.as_user("root@test.local")
    assert " · superadmin" in await build(root.id) and "agent_access" not in await build(root.id)


async def test_access_line_lists_toolsets_the_user_lacks(api):
    async with get_connections().postgres.rw() as s:
        await make_role(s, "chat_only", ["agent.chat"])
    u = await api.as_user("limited@x.io", roles=("chat_only",))
    text = await build(u.id)
    assert "agent_access: chưa được dùng trợ lý cho Tra cứu chung" in text
    full = await api.as_user("full@x.io")
    assert "agent_access" not in await build(full.id)


async def test_providers_run_in_order_then_name(api, monkeypatch):
    monkeypatch.setattr(context, "_PROVIDERS", {})  # chỉ provider của test (bỏ provider module, vd `tasks`)
    u = await api.as_user("p@x.io")
    context.register_context("zz", lines_fn("- zz"), order=10)
    context.register_context("bb", lines_fn("- bb"), order=20)
    context.register_context("aa", lines_fn("- aa"), order=20)
    context.register_context("first", lines_fn("- first"), order=1)
    assert [p.name for p in context.providers()] == ["first", "zz", "aa", "bb"]
    body = (await build(u.id)).splitlines()
    assert body[-5:-1] == ["- first", "- zz", "- aa", "- bb"]


async def test_budget_truncates_with_lookup_hint(api):
    u = await api.as_user("b@x.io")
    context.register_context("items", lines_fn(*[f"- i{i}" for i in range(5)]), budget=2)
    text = await build(u.id)
    assert "- i0\n- i1\n- còn 3 dòng items — dùng tool tra cứu" in text and "- i2" not in text
    context.register_context("fit", lines_fn("- a", "- b"), budget=2)
    assert "- a\n- b\n" in await build(u.id)


async def test_failing_provider_is_logged_and_skipped(api, bw_log):
    u = await api.as_user("f@x.io")

    async def boom(session, user):
        raise RuntimeError("hỏng")

    context.register_context("bad", boom, order=1)
    context.register_context("good", lines_fn("- ok"), order=2)
    text = await build(u.id)
    assert "- ok" in text and "bad" not in text
    assert [r["loc"] for r in bw_log() if r["loc"] == "agt0105"] == ["agt0105"]


def test_register_context_same_fn_is_idempotent_and_other_fn_is_error():
    fn = lines_fn("x")
    context.register_context("dup", fn)
    context.register_context("dup", fn, order=5)
    assert context._PROVIDERS["dup"].order == 5
    with pytest.raises(ValueError, match="đã đăng ký"):
        context.register_context("dup", lines_fn("y"))


async def test_short_only_uses_router_providers_and_caps_ten_lines(api):
    u = await api.as_user("s@x.io")
    assert await short(u.id) == "-"  # chưa provider nào góp
    context.register_context("private", lines_fn("- bí mật"))
    context.register_context("names", lines_fn(*[f"- n{i}" for i in range(12)]), router=True, order=1)
    context.register_context("tags", lines_fn("- tag"), router=True, order=2)
    out = await short(u.id)
    assert "bí mật" not in out and out.splitlines() == [*(f"- n{i}" for i in range(10)), "- tag"]
    assert await short(str(uuid.uuid4())) == "-"
    assert "- bí mật" in await build(u.id)  # khối đầy đủ vẫn có provider không phải router


async def test_context_for_user_without_roles(api):
    async with get_connections().postgres.rw() as s:
        u = await make_user(s, "norole@x.io", roles=())
    text = await build(str(u.id))
    assert "role -" in text
