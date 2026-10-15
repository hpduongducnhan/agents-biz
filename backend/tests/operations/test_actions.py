"""Danh mục action cho agent: chỉ operation `agent=True` mà principal được phép; gọi qua runner với source="agent" —
cùng kiểm quyền, cùng event log với web."""

import uuid
from dataclasses import replace

import pytest

from app.core.errors import AppException
from app.core.operations import registry
from app.core.operations.actions import call_action, list_actions
from app.core.operations.registry import get_spec
from app.core.security.principal import Principal

U1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
WRITER = Principal(user_id=U1, perms=frozenset({"fx.write"}))
READER = Principal(user_id=uuid.UUID("00000000-0000-4000-8000-000000000002"))
SUPER = Principal(user_id=uuid.UUID("00000000-0000-4000-8000-000000000009"), sup=True)


def fx_actions(principal):
    return {a.name: a for a in list_actions(principal) if a.name.startswith("fx.")}


def test_list_actions_only_agent_and_allowed():
    assert set(fx_actions(READER)) == {"fx.list_notes"}
    writer = fx_actions(WRITER)
    assert set(writer) == {"fx.list_notes", "fx.create_note"}
    info = writer["fx.create_note"]
    assert (info.effect, info.toolset, info.permission, info.superadmin) == ("write", "personal", "fx.write", False)
    assert "title" in info.input_schema["properties"]


def test_superadmin_sees_superadmin_actions(monkeypatch):
    spec = replace(get_spec("fx.purge"), name="fx.purge_agent", agent=True, toolset="admin")
    monkeypatch.setitem(registry._SPECS, spec.name, spec)
    assert "fx.purge_agent" not in fx_actions(WRITER)
    assert "fx.purge_agent" in fx_actions(SUPER)


async def test_call_action_hides_non_agent_and_unknown():
    for name in ("fx.delete_note", "khong.co"):
        with pytest.raises(AppException) as err:
            await call_action(name, WRITER, {}, agent_run_id=None)
        assert (err.value.code, err.value.status_code) == (1001, 404)


@pytest.mark.integration
async def test_call_action_runs_with_agent_source(op_env):
    run_id = uuid.uuid4()
    note = await call_action("fx.create_note", WRITER, {"title": "từ agent"}, agent_run_id=run_id)
    assert note.title == "từ agent"
    [entry] = op_env.events.entries
    assert entry.source == "agent" and entry.agent_run_id == run_id


@pytest.mark.integration
async def test_call_action_checks_permission_like_rest(op_env):
    with pytest.raises(AppException) as err:
        await call_action("fx.create_note", READER, {"title": "x"}, agent_run_id=None)
    assert err.value.code == 1005


@pytest.mark.integration
async def test_bad_args_come_back_as_structured_1002(op_env):
    with pytest.raises(AppException) as err:
        await call_action("fx.create_note", WRITER, {"title": ""}, agent_run_id=None)
    assert err.value.code == 1002 and err.value.data[0]["loc"] == ("title",)
