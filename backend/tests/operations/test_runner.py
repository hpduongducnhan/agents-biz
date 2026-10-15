"""run_operation: kiểm đăng nhập / superadmin / quyền / quyền nhóm, validate (1002), session đúng kênh, gửi sau commit
theo thứ tự (emit → data:changed → thông báo → event log), lỗi sau commit không làm hỏng thao tác."""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.cid import set_cid
from app.core.errors import AppException
from app.core.operations import registry, runner
from app.core.operations.context import PendingNotification
from app.core.operations.registry import get_spec
from app.core.operations.runner import run_operation, set_notifier
from app.core.security.principal import Principal
from app.observability.sinks import Sinks, set_sinks
from tests.fixtures.fx import ops as fx
from tests.fixtures.sinks import MemoryIssues

pytestmark = pytest.mark.integration
U1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
U2 = uuid.UUID("00000000-0000-4000-8000-000000000002")
U3 = uuid.UUID("00000000-0000-4000-8000-000000000003")
RUN = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
WRITER = Principal(user_id=U1, perms=frozenset({"fx.write"}))
READER = Principal(user_id=U2)
SUPER = Principal(user_id=uuid.UUID("00000000-0000-4000-8000-000000000009"), sup=True)


@pytest.fixture
def notified():
    got: list[PendingNotification] = []

    async def notifier(items):
        got.extend(items)

    set_notifier(notifier)
    yield got
    set_notifier(None)


def with_spec(monkeypatch, spec) -> str:
    monkeypatch.setitem(registry._SPECS, spec.name, spec)
    return spec.name


async def test_unknown_operation_is_1001(op_env):
    with pytest.raises(AppException) as err:
        await run_operation("fx.khong_co", WRITER, {})
    assert (err.value.code, err.value.status_code) == (1001, 404)


async def test_write_then_read_with_pagination(op_env):
    for title in ("một", "hai", "ba"):
        await run_operation("fx.create_note", WRITER, {"title": title})
    page = await run_operation("fx.list_notes", READER, {"limit": 2, "offset": 1})
    assert [n.title for n in page.items] == ["hai", "ba"] and (page.total, page.limit, page.offset) == (3, 2, 1)


async def test_limit_above_100_is_1002(op_env):
    with pytest.raises(AppException) as err:
        await run_operation("fx.list_notes", READER, {"limit": 101})
    assert (err.value.code, err.value.status_code) == (1002, 422)  # R14


async def test_missing_principal_is_1004(op_env):
    with pytest.raises(AppException) as err:
        await run_operation("fx.list_notes", None, {})
    assert (err.value.code, err.value.status_code) == (1004, 401)


async def test_permission_denied_is_1005_logged_and_event_logged(op_env, bw_log):
    with pytest.raises(AppException) as err:
        await run_operation("fx.create_note", READER, {"title": "x"})
    assert (err.value.code, err.value.status_code) == (1005, 403)
    assert any(line["loc"] == "sys0401" for line in bw_log())
    [entry] = op_env.events.entries
    assert (entry.ok, entry.error_code, entry.actor_id, entry.operation) == (False, 1005, U2, "fx.create_note")


async def test_superadmin_only_and_superadmin_bypass(op_env):
    with pytest.raises(AppException) as err:
        await run_operation("fx.purge", WRITER, None)
    assert err.value.code == 1005 and err.value.message == "Chỉ superadmin"
    await run_operation("fx.create_note", SUPER, {"title": "sa"})  # superadmin vượt permission
    assert await run_operation("fx.purge", SUPER, None) == {"purged": 1}


async def test_public_operation_runs_without_principal(op_env):
    assert await run_operation("fx.ping", None, None) == {"pong": True, "user": None}


async def test_invalid_input_is_1002_with_error_list(op_env):
    with pytest.raises(AppException) as err:
        await run_operation("fx.create_note", WRITER, {"title": ""})
    assert (err.value.code, err.value.status_code) == (1002, 422)
    assert err.value.data[0]["loc"] == ("title",)


async def test_read_operation_runs_on_read_only_session(op_env):
    with pytest.raises(DBAPIError) as err:
        await run_operation("fx.write_in_read", WRITER, None)
    assert "ReadOnlySqlTransaction" in type(err.value.orig).__name__


async def test_read_from_rw_is_still_read_only(op_env, monkeypatch):
    name = with_spec(monkeypatch, replace(get_spec("fx.write_in_read"), name="fx.write_in_read_rw", read_from="rw"))
    with pytest.raises(DBAPIError) as err:
        await run_operation(name, WRITER, None)
    assert "ReadOnlySqlTransaction" in type(err.value.orig).__name__


async def test_context_carries_channels_cid_and_caller(op_env, monkeypatch):
    seen: dict = {}

    async def probe(ctx):
        seen.update(bind=ctx.session.bind, redis=ctx.redis, mongo=ctx.mongo, settings=ctx.settings)
        seen.update(cid=ctx.cid, source=ctx.source, ip=ctx.request_ip)
        return {}

    base = replace(get_spec("fx.ping"), func=probe, public=False)
    ro = with_spec(monkeypatch, replace(base, name="fx.probe_ro"))
    set_cid("cidprobe1")
    await run_operation(ro, READER, None, request_ip="1.2.3.4")
    assert seen["bind"] is op_env.conns.postgres.ro_engine and seen["redis"] is op_env.conns.redis
    assert seen["mongo"] is None and seen["settings"] is op_env.settings
    assert (seen["cid"], seen["source"], seen["ip"]) == ("cidprobe1", "web", "1.2.3.4")
    rw = with_spec(monkeypatch, replace(base, name="fx.probe_rw", read_from="rw"))
    await run_operation(rw, READER, None)
    assert seen["bind"] is op_env.conns.postgres.rw_engine


async def test_after_commit_sends_in_order_and_event_logs(op_env, notified):
    note = await run_operation(
        "fx.create_note", WRITER, {"title": "x", "password": "bí mật"}, source="agent", agent_run_id=RUN
    )
    assert op_env.hub.events() == [
        ("sup", "fx:created", {"id": note.id}),
        (f"user.{U1}", "data:changed", {"keys": ["fx.notes"]}),
    ]
    expected = PendingNotification(user_id=U1, kind="fx_created", title="Đã tạo ghi chú", params={"id": note.id})
    assert notified == [expected]
    [entry] = op_env.events.entries
    assert (entry.ok, entry.error_code, entry.effect) == (True, None, "write")
    assert (entry.source, entry.agent_run_id) == ("agent", RUN)
    assert entry.input == {"title": "x", "password": "[REDACTED]"} and entry.duration_ms >= 0 and entry.cid


async def test_invalidate_reaches_extra_users(op_env):
    await run_operation("fx.share_note", WRITER, {"id": 1, "user_ids": [str(U2), str(U3)]})
    assert op_env.hub.events() == [
        (f"user.{U2}", "fx:shared", {"id": 1}),
        (f"user.{U3}", "fx:shared", {"id": 1}),
        (f"user.{U1}", "data:changed", {"keys": ["fx.notes"]}),
        (f"user.{U2}", "data:changed", {"keys": ["fx.notes", "fx.shared"]}),
        (f"user.{U3}", "data:changed", {"keys": ["fx.notes", "fx.shared"]}),
    ]


async def test_failed_write_rolls_back_and_sends_nothing(op_env, notified):
    with pytest.raises(AppException) as err:
        await run_operation("fx.create_then_fail", WRITER, {"title": "mất"})
    assert err.value.code == 1006
    assert op_env.hub.sent == [] and notified == [] and fx.HOOKS == []
    assert (await run_operation("fx.list_notes", READER, {})).items == []
    [entry] = op_env.events.entries
    assert (entry.ok, entry.error_code) == (False, 1006)


async def test_side_effect_failures_after_commit_do_not_fail_the_write(op_env, bw_log):
    class BrokenEventLog:
        async def write(self, entry):
            raise RuntimeError("mongo chết")

    async def broken_notifier(items):
        raise RuntimeError("notifier chết")

    op_env.hub.fail = True
    set_sinks(Sinks(event_log=BrokenEventLog(), issues=MemoryIssues(), enabled=True))
    set_notifier(broken_notifier)
    try:
        note = await run_operation("fx.create_note", WRITER, {"title": "vẫn ghi"})
    finally:
        set_notifier(None)
    assert note.title == "vẫn ghi"
    assert [n.title for n in (await run_operation("fx.list_notes", READER, {})).items] == ["vẫn ghi"]
    assert {"ws0501", "sys0404", "sys0405"} <= {line["loc"] for line in bw_log()}


async def test_after_commit_hook_runs_only_after_success(op_env):
    assert await run_operation("fx.with_hook", WRITER, None) == {"ok": True}
    assert fx.HOOKS == ["ran"]


async def test_read_operations_are_not_event_logged(op_env):
    await run_operation("fx.list_notes", READER, {})
    assert op_env.events.entries == []


async def test_missing_notifier_drops_with_one_warning(op_env, bw_log, monkeypatch):
    monkeypatch.setitem(runner._hooks, "warned", False)
    set_notifier(None)
    await run_operation("fx.create_note", WRITER, {"title": "a"})
    await run_operation("fx.create_note", WRITER, {"title": "b"})
    lines = [line for line in bw_log() if line["loc"] == "sys0403"]
    assert len(lines) == 1 and "DEFAULTS_APPLIED=[notifier=noop]" in lines[0]["msg"]  # R11
