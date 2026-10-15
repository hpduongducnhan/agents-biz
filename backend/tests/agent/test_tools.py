"""Tool dựng từ `@operation`: schema cho LLM, chạy dưới quyền user (source=agent), khoá / mặc định tham số."""

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain_core.tools import ToolException
from pydantic import BaseModel

from app.agent.runtime import tools
from app.core.errors import AppException
from app.core.operations.registry import get_spec
from app.domains import load_domains
from tests.agent.helpers import add_notes, make_rc, setup, unread


def by_name(rc):
    return {t.name: t for t in tools.build_tools(rc)}


class Out(BaseModel):
    x: int


def test_tool_name_and_render_result():
    assert tools.tool_name("notifications.mark_read") == "notifications_mark_read"
    assert tools.render_result("abc") == "abc" and tools.render_result({"a": "é"}) == '{"a": "é"}'
    assert json.loads(tools.render_result(Out(x=1))) == {"x": 1}


def test_render_result_is_always_json_for_models_lists_and_nested_dicts():
    class Item(BaseModel):
        id: uuid.UUID
        name: str
        at: datetime

    item = Item(id=uuid.UUID(int=1), name="Thông báo Ăn", at=datetime(2026, 10, 13, tzinfo=UTC))
    one = tools.render_result(item)
    assert json.loads(one) == {"id": str(uuid.UUID(int=1)), "name": "Thông báo Ăn", "at": "2026-10-13T00:00:00Z"}
    assert "Thông báo Ăn" in one and "Item(" not in one  # không str(model)
    listed = json.loads(tools.render_result([item, item]))
    assert [x["name"] for x in listed] == ["Thông báo Ăn", "Thông báo Ăn"]
    nested = json.loads(tools.render_result({"items": [item], "total": 1, "meta": {"ref": uuid.UUID(int=2)}}))
    assert nested["items"][0]["id"] == str(uuid.UUID(int=1)) and nested["meta"]["ref"] == str(uuid.UUID(int=2))
    assert json.loads(tools.render_result(None)) is None and json.loads(tools.render_result(42)) == 42
    assert tools.render_result("đã là chữ") == "đã là chữ"  # chuỗi giữ nguyên, không bọc JSON
    weird = json.loads(tools.render_result({"x": {1, 2}, "o": object}))  # kiểu lạ → fallback str, không ném lỗi
    assert set(weird) == {"x", "o"}


def test_result_truncated_at_20000():
    out = tools.render_result("x" * 25_000)
    assert out.startswith("x" * tools.RESULT_LIMIT) and out.endswith("(đã cắt, tổng 25000 ký tự)")
    assert len(out) < 20_100
    assert tools.render_result("y" * 20_000) == "y" * 20_000


def test_error_text_includes_code_message_and_data():
    plain = AppException(1001, status_code=404)
    assert tools.error_text(plain).startswith("Lỗi 1001: ")
    with_data = AppException(6003, status_code=422, data={"available": ["Ăn uống"]})
    assert tools.error_text(with_data).endswith('{"available": ["Ăn uống"]}') and "—" in tools.error_text(with_data)


def test_tool_schema_inlines_defs_and_hides_locked():
    load_domains()
    spec = get_spec("notifications.list")
    schema = tools.llm_schema(spec, locked={"unread_only": True}, defaults={"limit": 5})
    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    props = schema["properties"]
    assert "unread_only" not in props and props["limit"]["default"] == 5 and "offset" in props
    full = tools.llm_schema(get_spec("notifications.mark_read"), locked={}, defaults={})
    assert full["required"] == ["ids"]
    assert "required" not in tools.llm_schema(spec, locked={}, defaults={})


def test_real_args_fills_idempotency_key_deterministically():
    class WithKey(BaseModel):
        amount: int
        idempotency_key: str | None = None

    rc = SimpleNamespace(run_id=uuid.uuid4())
    spec = SimpleNamespace(input_model=WithKey)
    binding = SimpleNamespace(defaults={}, locked={}, spec=spec)
    token = tools.CALL_ID.set("call-1")
    try:
        key1 = tools.real_args(binding, {"amount": 5}, rc)["idempotency_key"]
        key2 = tools.real_args(binding, {}, rc)["idempotency_key"]
        given = tools.real_args(binding, {"idempotency_key": "mine"}, rc)["idempotency_key"]
    finally:
        tools.CALL_ID.reset(token)
    other = tools.CALL_ID.set("call-2")
    try:
        key3 = tools.real_args(binding, {}, rc)["idempotency_key"]
    finally:
        tools.CALL_ID.reset(other)
    assert key1.startswith("agent-") and key1 == key2 and key3 != key1 and given == "mine"
    no_key = SimpleNamespace(defaults={}, locked={}, spec=SimpleNamespace(input_model=None))
    assert "idempotency_key" not in tools.real_args(no_key, {"a": 1}, rc)


async def test_tool_runs_operation_as_user_with_source_agent(api, aenv, fake_llm, memory_sinks):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    await add_notes(u.id, 3)
    run_id = uuid.uuid4()
    rc = await make_rc(u, run_id=run_id)
    out = await by_name(rc)["notifications_unread_count"].ainvoke({})
    assert json.loads(out) == {"count": 3}
    out = await by_name(rc)["notifications_mark_all_read"].ainvoke({})
    assert json.loads(out)["updated"] == 3 and await unread(api, u) == 0
    entry = next(e for e in memory_sinks.events.entries if e.operation == "notifications.mark_all_read")
    assert entry.source == "agent" and entry.agent_run_id == run_id and entry.actor_id == uuid.UUID(u.id)
    stranger = await api.as_user("s@x.io")
    other = await add_notes(stranger.id, 1)
    out = await by_name(rc)["notifications_mark_read"].ainvoke({"ids": [str(other[0].id)]})
    assert json.loads(out)["updated"] == 0 and await unread(api, stranger) == 1  # id của người khác bị bỏ qua


async def test_business_error_becomes_text_not_exception(api, aenv, fake_llm):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    rc = await make_rc(u)
    text = await by_name(rc)["notifications_mark_read"].ainvoke({"ids": []})
    assert text.startswith("Lỗi 1002") or text.startswith("Lỗi 1")


async def test_locked_and_default_params_override_llm_values(api, aenv, fake_llm):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    await add_notes(u.id, 3)
    override = SimpleNamespace(policy=None, locked_params={"unread_only": True}, default_params={"limit": 2})
    rc = await make_rc(u, overrides={"notifications.list": override})
    tool = by_name(rc)["notifications_list"]
    assert "unread_only" not in tool.args_schema["properties"]
    out = json.loads(await tool.ainvoke({"unread_only": False}))  # LLM cố bỏ khoá
    assert out["limit"] == 2 and out["total"] == 3 and len(out["items"]) == 2


async def test_confirm_tool_refuses_without_approval_and_runs_with_it(api, aenv, fake_llm, confirm_write):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    notes = await add_notes(u.id, 2)
    rc = await make_rc(u)
    binding = next(b for b in tools.bindings(rc) if b.name == "notifications_mark_all_read")
    assert binding.policy == "confirm"
    with pytest.raises(ToolException) as exc:
        await tools.run_tool(binding, {}, rc)
    assert str(exc.value) == tools.CONFIRM_TEXT and await unread(api, u) == 2
    t1, t2 = tools.APPROVED_BY.set(str(u.id)), tools.APPROVED_ARGS.set({})
    try:
        out = await by_name(rc)["notifications_mark_all_read"].ainvoke({})
    finally:
        tools.APPROVED_BY.reset(t1)
        tools.APPROVED_ARGS.reset(t2)
    assert json.loads(out)["updated"] == len(notes) and await unread(api, u) == 0


async def test_unexpected_exception_becomes_system_error_text(api, aenv, fake_llm, monkeypatch):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    rc = await make_rc(u)

    async def boom(*_a, **_k):
        raise RuntimeError("db sập")

    monkeypatch.setattr(tools, "run_operation", boom)
    text = await by_name(rc)["notifications_list"].ainvoke({})
    assert text == "Lỗi 1000: lỗi hệ thống (RuntimeError)"
