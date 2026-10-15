"""Chống spam trợ lý: hạn mức chat theo tài khoản, tự chặn tạm, chặn tay, `agent.chat_limits`."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from app.agent.guard.models import AgentChatBlock
from app.core.connections.registry import get_connections
from app.notifications.models import Notification
from tests.agent.helpers import send, set_run, setup

pytestmark = pytest.mark.integration


@pytest.fixture
async def env(api, aenv, kicks, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    return api, u, stack.root


async def say(api, who, text="hi"):
    out = await send(api, who, text)
    await set_run(out["run_id"], status="done")  # tránh 6005 (một run mở / phiên)
    return out


async def err_data(api, who, i) -> dict:
    r = await api.call("POST", "/agent/send", who, json={"content": "hi", "client_msg_id": f"d{i}"})
    return r.json()


async def blocks(user_id: str | None = None) -> list[AgentChatBlock]:
    async with get_connections().postgres.ro() as s:
        stmt = select(AgentChatBlock).order_by(AgentChatBlock.created_at)
        return [b for b in (await s.exec(stmt)).all() if user_id is None or str(b.user_id) == user_id]


async def settings(api, root, **kw):
    await api.post("system.update_settings", root, **kw)


async def test_account_limit_third_message_is_6001_scope_account(env):
    api, u, root = env
    await settings(api, root, chat_per_minute=2, chat_autoblock=False)
    await say(api, u)
    await say(api, u)
    data = await err_data(api, u, 1)
    assert data["code"] == 6001 and data["data"]["scope"] == "account" and data["data"]["window"] == "minute"
    assert data["data"]["limit"] == 2


async def test_strikes_auto_block_with_403_6022(env):
    api, u, root = env
    await settings(api, root, chat_per_minute=1, chat_autoblock_strikes=2, chat_autoblock_window_min=10,
                   chat_autoblock_minutes=30)  # fmt: skip
    await say(api, u)
    first = await err_data(api, u, 1)
    assert first["code"] == 6001  # lần chạm thứ nhất: chưa chặn
    before = datetime.now(UTC)
    r = await api.call("POST", "/agent/send", u, json={"content": "hi", "client_msg_id": "d2"})
    body = r.json()
    assert r.status_code == 403 and body["code"] == 6022 and body["data"]["source"] == "auto"
    until_at = datetime.fromisoformat(body["data"]["until"])
    assert timedelta(minutes=29) < until_at - before < timedelta(minutes=31)
    rows = await blocks(u.id)
    assert len(rows) == 1 and rows[0].source == "auto" and rows[0].lifted_at is None
    again = await err_data(api, u, 3)
    assert again["code"] == 6022 and again["data"]["reason"]
    async with get_connections().postgres.ro() as s:
        kinds = (await s.exec(select(Notification.kind).where(Notification.user_id == rows[0].user_id))).all()
    assert "agent_chat_blocked" in kinds


async def test_second_auto_block_within_24h_doubles(env):
    api, u, root = env
    await settings(api, root, chat_per_minute=1, chat_autoblock_strikes=1, chat_autoblock_minutes=30)
    await say(api, u)
    first = await err_data(api, u, 1)
    assert first["code"] == 6022
    block = (await blocks(u.id))[0]
    await api.post("studio.unblock_chat", root, block_id=str(block.id))
    second = await err_data(api, u, 2)
    assert second["code"] == 6022
    rows = await blocks(u.id)
    assert len(rows) == 2
    minutes = (rows[1].until - rows[1].created_at).total_seconds() / 60
    assert 59.5 < minutes < 60.5


async def test_autoblock_off_only_6001_and_no_block(env):
    api, u, root = env
    await settings(api, root, chat_per_minute=1, chat_autoblock=False, chat_autoblock_strikes=1)
    await say(api, u)
    for i in range(3):
        assert (await err_data(api, u, i))["code"] == 6001
    assert await blocks(u.id) == []


async def test_superadmin_exempt_from_limits_and_blocks(env):
    api, u, root = env
    await settings(api, root, chat_per_minute=1, chat_autoblock_strikes=1)
    await say(api, root)
    await say(api, root)
    await say(api, root)
    assert await blocks(root.id) == []
    assert await api.err("POST", "studio.block_chat", root, json={"user_id": root.id, "minutes": 5, "reason": "x"}) == (
        409,
        2204,
    )


async def test_manual_block_unblock_and_open_ended(env):
    api, u, root = env
    out = await api.post("studio.block_chat", root, user_id=u.id, minutes=15, reason="Spam thử")
    assert out["source"] == "manual" and out["active"] is True and out["reason"] == "Spam thử"
    data = await err_data(api, u, 1)
    assert data["code"] == 6022 and data["data"]["reason"] == "Spam thử" and data["data"]["until"]
    await api.post("studio.unblock_chat", root, block_id=out["id"])
    assert (await say(api, u))["run_id"]
    forever = await api.post("studio.block_chat", root, user_id=u.id, minutes=None, reason="vô hạn")
    assert forever["until"] is None and forever["active"] is True
    assert (await err_data(api, u, 2))["data"]["until"] is None


async def test_block_replaces_existing_open_block(env):
    api, u, root = env
    first = await api.post("studio.block_chat", root, user_id=u.id, minutes=15, reason="một")
    second = await api.post("studio.block_chat", root, user_id=u.id, minutes=60, reason="hai")
    rows = {str(b.id): b for b in await blocks(u.id)}
    assert rows[first["id"]].lifted_at is not None and rows[second["id"]].lifted_at is None
    active = await api.get("studio.list_chat_blocks", root, active_only=True)
    assert [b["id"] for b in active["items"]] == [second["id"]]


async def test_expired_block_not_active_and_list_filters(env):
    api, u, root = env
    out = await api.post("studio.block_chat", root, user_id=u.id, minutes=15, reason="sắp hết")
    async with get_connections().postgres.rw() as s:
        row = await s.get(AgentChatBlock, uuid.UUID(out["id"]))
        row.until = datetime.now(UTC) - timedelta(minutes=1)
        s.add(row)
    assert (await say(api, u))["run_id"]  # hết hạn → gửi được
    everything = await api.get("studio.list_chat_blocks", root)
    assert [b["active"] for b in everything["items"]] == [False] and everything["total"] == 1
    assert (await api.get("studio.list_chat_blocks", root, active_only=True))["total"] == 0


async def test_studio_chat_ops_are_superadmin_only(env):
    api, u, root = env
    out = await api.post("studio.block_chat", root, user_id=u.id, minutes=5, reason="x")
    assert await api.err("GET", "studio.list_chat_blocks", u) == (403, 1005)
    assert await api.err("POST", "studio.block_chat", u, json={"user_id": u.id, "minutes": 5, "reason": "x"}) == (
        403,
        1005,
    )
    assert await api.err("POST", "studio.unblock_chat", u, json={"block_id": out["id"]}) == (403, 1005)


async def test_block_chat_validates_reason_and_minutes(env):
    api, u, root = env
    assert (await api.err("POST", "studio.block_chat", root, json={"user_id": u.id, "minutes": 5, "reason": ""}))[
        0
    ] == 422
    assert (await api.err("POST", "studio.block_chat", root, json={"user_id": u.id, "minutes": 0, "reason": "x"}))[
        0
    ] == 422


async def test_chat_limits_windows_used_and_blocked(env):
    api, u, root = env
    out = await api.get("agent.chat_limits", u)
    assert out["exempt"] is False and out["blocked"] is None
    assert [(w["window"], w["limit"], w["used"], w["source"]) for w in out["windows"]] == [
        ("minute", 10, 0, "default"), ("hour", 100, 0, "default"), ("day", 400, 0, "default")]  # fmt: skip
    await say(api, u)
    out = await api.get("agent.chat_limits", u)
    assert [w["used"] for w in out["windows"]] == [1, 1, 1]
    await api.post("studio.block_chat", root, user_id=u.id, minutes=15, reason="r")
    out = await api.get("agent.chat_limits", u)
    assert out["blocked"]["reason"] == "r" and out["blocked"]["source"] == "manual"
    sup = await api.get("agent.chat_limits", root)
    assert sup["exempt"] is True and all(w["limit"] is None for w in sup["windows"])


async def test_unlimited_window_reported_as_null(env):
    api, u, root = env
    await settings(api, root, chat_per_hour=0)
    out = await api.get("agent.chat_limits", u)
    assert next(w for w in out["windows"] if w["window"] == "hour")["limit"] is None
