"""Dọn run treo mỗi 30 s + task `agent.run` / `agent.resume`."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.agent import tasks
from tests.agent.helpers import add_approval, approvals, events_of, run_row, send, set_run, setup


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm):
    await setup(api, fake_llm.base_url)
    return api, await api.as_user("u@x.io"), rt, kicks


async def new_run(api, u, status: str, text: str = "x", **values):
    sent = await send(api, u, text)
    await set_run(sent["run_id"], status=status, **values)
    return sent


async def test_sweep_marks_stale_runs_failed_and_expires_approvals(env):
    api, u, rt, kicks = env
    now = datetime.now(UTC)
    stale = await new_run(api, u, "running", heartbeat_at=now - timedelta(seconds=200))
    fresh = await new_run(api, u, "running", heartbeat_at=now - timedelta(seconds=10))
    old_queue = await new_run(api, u, "queued", created_at=now - timedelta(minutes=11))
    new_queue = await new_run(api, u, "queued")
    waiting = await new_run(api, u, "waiting_approval")
    expired = await add_approval(waiting["run_id"], expires_in=-10)
    live = await add_approval(waiting["run_id"], expires_in=3600)
    kicks.reset_mock()
    out = await tasks.sweep_runs()
    assert out == {"failed": 2, "expired": 1, "resumed": 0}
    for sent in (stale, old_queue):
        run = await run_row(sent["run_id"])
        assert (run.status, run.error_code) == ("failed", 6015) and run.ended_at
    assert (await run_row(fresh["run_id"])).status == "running" and (
        await run_row(new_queue["run_id"])
    ).status == "queued"
    errors = [d["code"] for e, d in events_of(rt, u.id, "agent:error")]
    assert errors == [6015, 6015]
    states = {a.id: a.status for a in await approvals(waiting["run_id"])}
    assert states == {expired.id: "expired", live.id: "pending"}
    assert (await run_row(waiting["run_id"])).status == "waiting_approval"  # còn yêu cầu đang chờ
    kicks.assert_not_awaited()


async def test_sweep_resumes_waiting_runs_with_every_approval_decided_or_expired(env):
    api, u, _, kicks = env
    waiting = await new_run(api, u, "waiting_approval")
    await add_approval(waiting["run_id"], expires_in=-10)  # hết hạn → LLM nhận "hết hạn duyệt"
    await add_approval(waiting["run_id"], status="approved")
    other = await new_run(api, u, "waiting_approval")
    await add_approval(other["run_id"], expires_in=3600)
    kicks.reset_mock()
    out = await tasks.sweep_runs()
    assert out["expired"] == 1 and out["resumed"] == 1
    kicks.assert_awaited_once_with(str(uuid.UUID(waiting["run_id"])))
    again = await tasks.sweep_runs()  # không còn gì cần dọn trừ run đã sẵn sàng resume lỡ kick
    assert again["failed"] == 0 and again["expired"] == 0


async def test_sweep_when_nothing_to_do_is_quiet(env):
    assert await tasks.sweep_runs() == {"failed": 0, "expired": 0, "resumed": 0}


async def test_run_turn_chains_resume_only_when_runner_asks(env, monkeypatch):
    api, u, _, kicks = env
    calls = []

    async def fake_execute(run_id):
        calls.append(("execute", run_id))
        return run_id == "again"

    async def fake_resume(run_id):
        calls.append(("resume", run_id))
        return False

    monkeypatch.setattr(tasks.runner, "execute", fake_execute)
    monkeypatch.setattr(tasks.runner, "resume", fake_resume)
    kicks.reset_mock()
    await tasks.run_turn("plain")
    kicks.assert_not_awaited()
    await tasks.run_turn("again")
    kicks.assert_awaited_once_with("again")
    await tasks.resume_turn("r1")
    assert calls == [("execute", "plain"), ("execute", "again"), ("resume", "r1")]
