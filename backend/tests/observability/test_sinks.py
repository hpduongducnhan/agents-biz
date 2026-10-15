"""Sink quan sát: mặc định Noop; init ở hai chế độ Mongo (process không cần log luôn Noop), báo một lần;
capture_issue không ném."""

import uuid
from datetime import UTC, datetime

import pytest

from app import observability as obs
from app.core.cid import set_cid
from app.core.settings import Settings
from app.observability.sinks import (
    EventLogEntry,
    NoopEventLogSink,
    NoopIssueSink,
    Sinks,
    capture_issue,
    get_sinks,
    noop_sinks,
    set_sinks,
)
from tests.fixtures.sinks import MemoryEventLog, MemoryIssues


@pytest.fixture(autouse=True)
def restore_noop():
    yield
    set_sinks(noop_sinks())


def entry() -> EventLogEntry:
    return EventLogEntry(
        ts=datetime.now(UTC),
        cid="c1",
        actor_id=uuid.uuid4(),
        actor_sup=False,
        source="web",
        agent_run_id=None,
        operation="fx.create_note",
        effect="write",
        input={"title": "a"},
        ok=True,
        error_code=None,
        duration_ms=3,
    )


async def test_default_sinks_are_noop_and_accept_everything():
    sinks = get_sinks()
    assert sinks.enabled is False
    assert isinstance(sinks.event_log, NoopEventLogSink) and isinstance(sinks.issues, NoopIssueSink)
    await sinks.event_log.write(entry())
    await sinks.issues.capture(RuntimeError("x"), source="task", loc=None, cid=None, context={})


@pytest.mark.parametrize(("mongo_enabled", "loc"), [(True, "obs0002"), (False, "obs0001")])
async def test_init_observability_sets_noop_in_both_modes(mongo_enabled, loc, monkeypatch, bw_log):
    monkeypatch.setitem(obs._state, "warned", False)
    set_sinks(Sinks(event_log=MemoryEventLog(), issues=MemoryIssues(), enabled=True))
    sinks = await obs.init_observability(Settings(_env_file=None, MONGO_ENABLED=mongo_enabled), None)
    assert sinks is get_sinks() and sinks.enabled is False
    [line] = [line for line in bw_log() if line["loc"] in ("obs0001", "obs0002")]
    assert line["loc"] == loc and "DEFAULTS_APPLIED=[sinks=noop]" in line["msg"]  # R11


async def test_noop_fallback_is_logged_once_per_process(monkeypatch, bw_log):
    monkeypatch.setitem(obs._state, "warned", False)
    off = Settings(_env_file=None, MONGO_ENABLED=False)
    await obs.init_observability(off, None)
    await obs.init_observability(off, None)
    assert [line["loc"] for line in bw_log()].count("obs0001") == 1


async def test_close_observability_falls_back_to_noop():
    set_sinks(Sinks(event_log=MemoryEventLog(), issues=MemoryIssues(), enabled=True))
    await obs.close_observability()
    assert get_sinks().enabled is False


async def test_capture_issue_passes_cid_and_context(memory_sinks):
    set_cid("cidissue1")
    await capture_issue(ValueError("hỏng"), source="task", loc="tq0500", context={"task": "fx.x"})
    [item] = memory_sinks.issues.items
    assert (item["source"], item["loc"], item["cid"]) == ("task", "tq0500", "cidissue1")
    assert item["context"] == {"task": "fx.x"} and isinstance(item["exc"], ValueError)


async def test_broken_issue_sink_is_logged_not_raised(bw_log):
    class Broken:
        async def capture(self, exc, **kwargs):
            raise RuntimeError("mongo chết")

    set_sinks(Sinks(event_log=MemoryEventLog(), issues=Broken(), enabled=True))
    await capture_issue(RuntimeError("x"), source="consumer")
    assert any(line["loc"] == "obs0501" for line in bw_log())
