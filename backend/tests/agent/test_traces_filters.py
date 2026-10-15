"""traces.list: lọc theo có lỗi, model, user, trạng thái + `names`; chỉ mục Mongo của calls / spans;
`TraceSink` tắt (Noop) cho các hàm calls."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pymongo import AsyncMongoClient

from app.observability.sinks import get_sinks
from app.observability.traces import NoopTraceSink
from tests.agent.helpers import setup
from tests.agent.mongo_stack import call_doc, put_calls, put_run, stack  # noqa: F401


class World:
    pass


@pytest.fixture
async def world(stack):  # noqa: F811
    if not stack.mongo:
        pytest.skip("cần Mongo bật")
    api = stack.api
    s = await setup(api, stack.llm_url)
    w = World()
    w.api, w.root, w.agent, w.stack = api, s.root, s.agent_id, stack
    w.ua, w.ub = await api.as_user("a@x.io", name="An"), await api.as_user("b@x.io", name="Bình")
    ua, ub = w.ua.id, w.ub.id
    t = datetime.now(UTC)
    w.r1 = await put_run(user_id=ua, agent_id=w.agent, models=["m1"], start=t - timedelta(hours=3))
    w.r2 = await put_run(user_id=ua, agent_id=w.agent, models=["m1", "m2"], llm_errors=1, start=t - timedelta(hours=2))
    w.r3 = await put_run(user_id=ub, models=["m2"], status="error", start=t - timedelta(hours=1))
    w.r4 = await put_run(user_id=ub, start=t - timedelta(minutes=10))  # lượt cũ: không model, llm_errors 0
    return w


async def ids(w, **q):
    out = await w.api.get("traces.list", w.root, **q)
    return [i["id"] for i in out["items"]], out


async def test_user_filter(world):
    w = world
    assert set((await ids(w, user_id=w.ua.id))[0]) == {w.r1["id"], w.r2["id"]}
    assert set((await ids(w, user_id=w.ub.id))[0]) == {w.r3["id"], w.r4["id"]}
    assert (await ids(w, user_id=str(uuid.uuid4())))[0] == []
    assert await w.api.err("GET", "traces.list", w.root, params={"user_id": "nonsense"}) == (422, 1002)


async def test_has_error_true_and_false(world):
    w = world
    bad, _ = await ids(w, has_error="true")
    good, _ = await ids(w, has_error="false")
    assert set(bad) == {w.r2["id"], w.r3["id"]}  # r2: run ok nhưng có lần gọi LLM lỗi; r3: run lỗi
    assert set(good) == {w.r1["id"], w.r4["id"]} and not set(bad) & set(good)
    assert (await ids(w, has_error="true", status="error"))[0] == [w.r3["id"]]
    assert (await ids(w, has_error="false", status="ok"))[0] == [w.r4["id"], w.r1["id"]]
    assert (await ids(w, has_error="true", user_id=w.ua.id))[0] == [w.r2["id"]]


async def test_model_filter_and_combination(world):
    w = world
    assert set((await ids(w, model="m1"))[0]) == {w.r1["id"], w.r2["id"]}
    assert set((await ids(w, model="m2"))[0]) == {w.r2["id"], w.r3["id"]}
    assert (await ids(w, model="m2", user_id=w.ub.id))[0] == [w.r3["id"]]
    assert (await ids(w, model="nope"))[0] == []
    assert (await ids(w, model="m1", has_error="true", user_id=w.ua.id))[0] == [w.r2["id"]]


async def test_response_names_for_users_and_agents(world):
    w = world
    _, out = await ids(w)
    names = out["names"]
    assert names[f"user:{w.ua.id}"] == "An" and names[f"user:{w.ub.id}"] == "Bình"
    assert names[f"agent:{w.agent}"] == "Assistant"
    _, only_a = await ids(w, user_id=w.ua.id)
    assert set(only_a["names"]) == {f"user:{w.ua.id}", f"agent:{w.agent}"}
    _, empty = await ids(w, model="nope")
    assert empty["names"] == {} and empty["total"] == 0


async def test_run_summary_fields_round_trip_and_legacy_run(world):
    w = world
    _, out = await ids(w, user_id=w.ua.id, has_error="true")
    (item,) = out["items"]
    assert item["models"] == ["m1", "m2"] and item["llm_errors"] == 1
    legacy = next(i for i in (await ids(w))[1]["items"] if i["id"] == w.r4["id"])
    assert legacy["models"] == [] and legacy["cost"] is None and legacy["llm_errors"] == 0


async def test_new_indexes_exist(world):
    settings = world.stack.settings
    client = AsyncMongoClient(settings.MONGO_RW_URL)
    try:
        db = client[settings.MONGO_DB_NAME]
        calls = [tuple(v["key"]) for v in (await db["agent_llm_calls"].index_information()).values()]
        assert (("expire_at", 1),) in calls and (("at", -1),) in calls
        for field in ("user_id", "model_id", "credential_id", "status"):
            assert ((field, 1), ("at", -1)) in calls, field
        info = await db["agent_llm_calls"].index_information()
        assert any(v.get("expireAfterSeconds") == 0 and v["key"] == [("expire_at", 1)] for v in info.values())
        spans = [tuple(v["key"]) for v in (await db["agent_spans"].index_information()).values()]
        for field in ("user_id", "session_id", "status"):
            assert (("kind", 1), (field, 1), ("start", -1)) in spans, field
    finally:
        await client.close()


async def test_calls_sink_roundtrip_on_mongo(world):
    sink = get_sinks().traces
    at = datetime.now(UTC) - timedelta(minutes=1)
    docs = [call_doc(at=at - timedelta(seconds=i), model="rt-model", input_tokens=i) for i in range(3)]
    await put_calls(*docs)
    rows, total = await sink.list_calls({"model": "rt-model"}, limit=2, offset=0)
    assert total == 3 and [r["input_tokens"] for r in rows] == [0, 1] and rows[0]["id"] == docs[0]["id"]
    rows, _ = await sink.list_calls({"model": "rt-model"}, limit=2, offset=2)
    assert [r["input_tokens"] for r in rows] == [2]
    agg = await sink.aggregate_calls(
        [{"$match": {"model": "rt-model"}}, {"$group": {"_id": None, "n": {"$sum": 1}, "t": {"$sum": "$input_tokens"}}}]
    )
    assert agg == [{"_id": None, "n": 3, "t": 3}]


async def test_noop_sink_calls_do_nothing():
    sink = NoopTraceSink()
    assert await sink.save_call({"id": "x"}) is None
    assert await sink.aggregate_calls([{"$match": {}}]) == []
    assert await sink.list_calls({}, limit=5, offset=0) == ([], 0)
    assert sink.enabled is False


async def test_traces_list_disabled_when_mongo_off(stack):  # noqa: F811
    if stack.mongo:
        pytest.skip("cần Mongo tắt")
    root = (await setup(stack.api, stack.llm_url)).root
    out = await stack.api.get("traces.list", root, has_error="true", model="m")
    assert out["enabled"] is False and out["items"] == [] and out["names"] == {}
