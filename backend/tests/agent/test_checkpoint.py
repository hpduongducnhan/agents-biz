"""Checkpointer (R20): dùng chung một saver; không dựng được → None + WARNING một lần `DEFAULTS_APPLIED`."""

from app.agent.runtime import checkpoint
from app.core.connections.registry import get_connections


async def test_checkpointer_is_shared_and_drop_is_safe(aenv):
    first = await checkpoint.get_checkpointer()
    assert first is not None and await checkpoint.get_checkpointer() is first
    await checkpoint.drop("không-có-thread")  # xoá thread chưa tồn tại vô hại


async def test_checkpointer_unavailable_returns_none_and_warns_once(aenv, monkeypatch, bw_log):
    async def boom(*_a, **_k):
        raise ConnectionError("pg down")

    monkeypatch.setattr(get_connections().postgres, "raw_pool", boom)
    assert await checkpoint.get_checkpointer() is None and await checkpoint.get_checkpointer() is None
    warns = [r for r in bw_log() if r.get("loc") == "agt0401"]
    assert len(warns) == 1 and "DEFAULTS_APPLIED=[checkpointer]" in warns[0]["msg"]
    await checkpoint.drop("x")  # không có saver → bỏ qua
