"""@task: kiq vào queue theo lane, giữ cid, retry rồi ghi issue lần cuối; lịch cron / every cho scheduler."""

import asyncio
import contextlib
from dataclasses import replace

import aio_pika
import pytest
from taskiq import TaskiqMessage, TaskiqResult
from taskiq.api import run_receiver_task

from app.core.cid import set_cid
from app.core.messaging import tasks as tasks_mod
from app.core.messaging.lanes import task_queue
from app.core.messaging.tasks import (
    ErrorMiddleware,
    TaskScheduleSource,
    all_tasks,
    build_task_broker,
    register_tasks,
    task,
    task_labels,
)
from app.core.settings import Settings
from tests.conftest import reset_rabbit, until
from tests.fixtures.fx import tasks as fx


def test_task_declaration_rules():
    with pytest.raises(ValueError, match="trùng"):
        task("fx.tally")(fx.tally.spec.func)
    with pytest.raises(ValueError, match="cron"):
        task("fx.both", cron="* * * * *", every=5)
    with pytest.raises(ValueError, match="<miền>.<việc>"):
        task("tally")
    with pytest.raises(ValueError, match="lane"):
        task("fx.lost", lane="khong-co")
    with pytest.raises(TypeError, match="async"):
        task("fx.sync_one")(lambda: None)


async def test_direct_call_runs_function():
    fx.SEEN.clear()
    await fx.tally(9)
    assert fx.SEEN[0][:2] == ("tally", 9)


def test_labels_follow_lane_retry_timeout():
    assert task_labels(fx.tally.spec) == {"queue_name": "bw.tq.default", "retry_on_error": True, "max_retries": 2}
    assert task_labels(fx.slow.spec)["queue_name"] == "bw.tq.agent-run"
    assert task_labels(fx.tick.spec) == {"queue_name": "bw.tq.default"}
    assert task_labels(replace(fx.tally.spec, timeout=5.0))["timeout"] == 5.0


def test_interval_resolves_callable_and_clamps():
    s = Settings(_env_file=None, HEARTBEAT_INTERVAL=0.2)
    assert fx.tick.spec.interval(s) == 1
    assert replace(fx.tick.spec, every=lambda st: st.HEARTBEAT_INTERVAL * 100).interval(s) == 20
    assert fx.tally.spec.interval(s) is None


async def test_schedule_source_lists_periodic_tasks_with_fresh_cid():
    source = TaskScheduleSource(Settings(_env_file=None))
    found = {t.task_name: t for t in await source.get_schedules()}
    assert "fx.tally" not in found
    tick = found["fx.tick"]
    assert tick.interval == 1 and tick.cron is None and tick.labels["queue_name"] == "bw.tq.default"
    source.pre_send(tick)
    first = tick.labels["cid"]
    source.pre_send(tick)
    assert tick.labels["cid"] != first  # mỗi lần cron là điểm khởi đầu chuỗi → cid mới


async def test_rounded_every_is_logged_once(monkeypatch, bw_log):
    half = replace(fx.tick.spec, name="fx.half_second", every=0.5)
    monkeypatch.setitem(tasks_mod._TASKS, half.name, half)
    source = TaskScheduleSource(Settings(_env_file=None))
    await source.get_schedules()
    found = {t.task_name: t for t in await source.get_schedules()}
    assert found["fx.half_second"].interval == 1
    lines = [line for line in bw_log() if line["loc"] == "tq0101"]
    assert len(lines) == 1 and "DEFAULTS_APPLIED=[every=1]" in lines[0]["msg"]  # R11


async def test_error_middleware_captures_only_the_final_attempt(memory_sinks, bw_log):
    mw = ErrorMiddleware()
    labels = {"queue_name": "bw.tq.default", "retry_on_error": True, "max_retries": 2}
    result = TaskiqResult(is_err=True, return_value=None, execution_time=0.0)
    first = TaskiqMessage(
        task_id="t1", task_name="fx.always_fail", labels={**labels, "_retries": 0}, args=[], kwargs={}
    )
    last = TaskiqMessage(task_id="t1", task_name="fx.always_fail", labels={**labels, "_retries": 1}, args=[], kwargs={})
    await mw.on_error(first, result, RuntimeError("x"))
    assert memory_sinks.issues.items == []
    await mw.on_error(last, result, RuntimeError("x"))
    [issue] = memory_sinks.issues.items
    assert issue["context"] == {"task": "fx.always_fail", "task_id": "t1", "attempts": 2}
    assert [line["loc"] for line in bw_log()].count("tq0500") == 2


@pytest.fixture
async def worker(messaging_env):
    await reset_rabbit(messaging_env, queues=["bw.tq.default", "bw.tq.agent-run", "bw.tq.dead_letter"])
    fx.SEEN.clear()
    started = []

    async def start(lanes):
        broker = build_task_broker(messaging_env.RABBITMQ_URL, [task_queue(x) for x in lanes], worker=True)
        register_tasks(broker, all_tasks())
        await broker.startup()
        started.append((broker, asyncio.create_task(run_receiver_task(broker))))

    yield start
    for broker, job in started:
        job.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await job
        await broker.shutdown()


@pytest.mark.integration
async def test_kiq_runs_on_worker_with_cid(worker):
    await worker(["default"])
    set_cid("taskcid1")
    await fx.tally.kiq(3)
    assert await until(lambda: fx.SEEN)
    assert fx.SEEN == [("tally", 3, "taskcid1")]


@pytest.mark.integration
async def test_worker_only_takes_its_lanes(worker, messaging_env):
    await worker(["default"])
    await fx.slow.kiq(1)
    await fx.tally.kiq(2)
    assert await until(lambda: fx.SEEN)
    await asyncio.sleep(0.3)
    assert [n for _, n, _ in fx.SEEN] == [2]
    conn = await aio_pika.connect(messaging_env.RABBITMQ_URL)
    try:
        q = await (await conn.channel()).declare_queue("bw.tq.agent-run", passive=True)
    finally:
        await conn.close()
    assert q.declaration_result.message_count == 1


@pytest.mark.integration
async def test_failed_task_retries_then_captures_one_issue(worker, bw_log, memory_sinks):
    await worker(["default"])
    await fx.always_fail.kiq(5)
    assert await until(lambda: memory_sinks.issues.items, timeout=8)
    await asyncio.sleep(0.3)
    assert [line["loc"] for line in bw_log()].count("tq0500") == 2  # retry=1 → chạy 2 lần
    [issue] = memory_sinks.issues.items
    assert issue["source"] == "task" and issue["context"]["attempts"] == 2
