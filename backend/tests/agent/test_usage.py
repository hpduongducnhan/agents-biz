"""Usage giám sát: công thức giá, `usage.summary` theo từng chiều / bộ lọc / ngày / giờ, `usage.errors`
trên Mongo thật; Mongo tắt → `enabled: false`."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.agent.config.models import AgentModel
from app.agent.trace import usage
from app.core.connections.registry import get_connections
from app.tenants.models import DEFAULT_TENANT_ID
from tests.agent.helpers import chat, setup
from tests.agent.mongo_stack import call_doc, put_calls, stack  # noqa: F401
from tests.auth.factories import make_tenant

PRICED = {
    "input_price_per_1m": "3",
    "output_price_per_1m": "15",
    "cache_read_price_per_1m": "0.3",
    "cache_write_price_per_1m": "3.75",
}


def priced_model() -> AgentModel:
    prices = {k: Decimal(v) for k, v in PRICED.items()}
    return AgentModel(provider_id=uuid.uuid4(), model_id="m", name="m", **prices)


def test_cost_formula_with_cache_tokens():
    model = priced_model()
    used = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "input_token_details": {"cache_read": 400, "cache_creation": 100},
    }
    t = usage.tokens_of(used)
    assert t == {"input_tokens": 500, "output_tokens": 500, "cache_read_tokens": 400, "cache_write_tokens": 100}
    assert usage.cost_of(model, t) == Decimal("0.009495")
    assert usage.tokens_of({}) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    assert usage.tokens_of({"input_tokens": 10, "input_token_details": {"cache_read": 50}})["input_tokens"] == 0
    free = AgentModel(provider_id=uuid.uuid4(), model_id="f", name="f")
    assert usage.cost_of(free, t) == Decimal("0.000000")


async def test_run_cost_accumulates(api, aenv, rt, kicks, fake_llm):
    await setup(api, fake_llm.base_url, **PRICED)
    u = await api.as_user("u@x.io")
    sent, run = await chat(api, u, "call:notifications_list {}")  # hai lần gọi LLM
    assert run.status == "done" and run.cost > 0 and sent


async def test_free_model_run_cost_is_zero(api, aenv, rt, kicks, fake_llm):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    _, run = await chat(api, u, "miễn phí")
    assert run.cost == 0


# ── usage.summary / usage.errors trên Mongo thật ─────────────────────────────────────────────────────────────────────
class World:
    """Hai user, hai agent, hai model, hai key + 6 lần gọi ở các thời điểm khác nhau."""


@pytest.fixture
async def world(stack):  # noqa: F811
    if not stack.mongo:
        pytest.skip("cần Mongo bật")
    api = stack.api
    s = await setup(api, stack.llm_url, **PRICED)
    root = s.root
    w = World()
    w.stack, w.api, w.root, w.tz = stack, api, root, ZoneInfo(stack.settings.APP_TIMEZONE)
    m2 = await api.post("studio.save_model", root, provider_id=s.provider_id, model_id="m2", name="Model Hai")
    a2 = await api.post("studio.save_agent", root, slug="second", name="Agent Hai")
    w.cred2 = (await api.post("credentials.create", root, name="key-hai", secret="sk-key-two-12345678"))["id"]
    w.ua, w.ub = await api.as_user("a@x.io", name="An"), await api.as_user("b@x.io", name="Bình")
    w.p, w.m1, w.m2, w.a1, w.a2, w.c1 = s.provider_id, s.model_id, m2["id"], s.agent_id, a2["id"], s.cred_id
    w.s_a, w.s_b = str(uuid.uuid4()), str(uuid.uuid4())
    base = (datetime.now(UTC) - timedelta(days=3)).replace(hour=2, minute=30, second=0, microsecond=0)
    w.base = base
    common = {"provider_id": w.p, "provider_kind": "openai_compatible"}
    w.docs = {
        "ok_a": call_doc(
            at=base,
            user_id=w.ua.id,
            session_id=w.s_a,
            agent_id=w.a1,
            agent_slug="assistant",
            model_id=w.m1,
            credential_id=w.c1,
            input_tokens=1000,
            output_tokens=100,
            cache_read_tokens=50,
            cache_write_tokens=10,
            cost=0.5,
            latency_ms=200,
            **common,
        ),
        "ok_b": call_doc(
            at=base + timedelta(minutes=20),
            user_id=w.ub.id,
            session_id=w.s_b,
            agent_id=w.a2,
            agent_slug="second",
            model_id=w.m2,
            model="m2",
            credential_id=w.cred2,
            input_tokens=2000,
            output_tokens=200,
            cost=0.25,
            latency_ms=400,
            **common,
        ),
        "router_rate": call_doc(
            at=base + timedelta(hours=1),
            user_id=w.ub.id,
            session_id=w.s_b,
            agent_id=w.a2,
            agent_slug="second",
            model_id=w.m2,
            model="m2",
            credential_id=w.cred2,
            purpose="router",
            status="error",
            error_kind="rate",
            error="429 Rate limit",
            latency_ms=50,
            input_tokens=0,
            output_tokens=0,
            **common,
        ),
        "nokey_server": call_doc(
            at=base + timedelta(hours=1, minutes=5),
            user_id=w.ub.id,
            session_id=w.s_b,
            agent_id=w.a2,
            agent_slug="second",
            model_id=w.m2,
            model="m2",
            credential_id=None,
            key_hint=None,
            status="error",
            error_kind="server",
            error="500 boom",
            latency_ms=30,
            input_tokens=0,
            output_tokens=0,
            **common,
        ),
        "old_other": call_doc(
            at=base - timedelta(days=2),
            user_id=w.ua.id,
            session_id=w.s_a,
            agent_id=w.a1,
            agent_slug="assistant",
            model_id=w.m1,
            credential_id=w.c1,
            status="error",
            error_kind="other",
            error="lạ",
            latency_ms=10,
            input_tokens=0,
            output_tokens=0,
            **common,
        ),
        "ghost": call_doc(  # agent / model / provider đã xoá khỏi Postgres → tên lấy từ document
            at=base + timedelta(hours=2),
            user_id=w.ua.id,
            agent_slug="ghost-agent",
            model="ghost-model",
            provider_kind="anthropic",
            credential_id=None,
            input_tokens=10,
            output_tokens=1,
            cost=0.01,
            latency_ms=90,
        ),
    }
    await put_calls(*w.docs.values())
    return w


def by_key(out):
    return {r["key"]: r for r in out["rows"]}


async def test_summary_total_and_error_breakdown(world):
    out = await world.api.get("usage.summary", world.root, group_by="provider")
    assert out["enabled"] and out["group_by"] == "provider" and out["tz"] == world.stack.settings.APP_TIMEZONE
    t = out["total"]
    assert t["requests"] == 6 and t["input_tokens"] == 3010 and t["output_tokens"] == 301
    assert t["cache_read_tokens"] == 50 and t["cache_write_tokens"] == 10 and t["cost"] == pytest.approx(0.76)
    assert (t["errors"], t["errors_rate"], t["errors_auth"], t["errors_server"], t["errors_other"]) == (3, 1, 0, 1, 1)
    assert t["latency_avg_ms"] == (200 + 400 + 90) // 3  # chỉ tính lần gọi ok
    rows = by_key(out)
    assert rows[world.p]["name"] == "fake" and rows[world.p]["sub"] == "openai_compatible"
    assert rows[world.p]["requests"] == 5


async def test_summary_group_by_every_dimension(world):
    api, root = world.api, world.root
    out = await api.get("usage.summary", root, group_by="model")
    rows = by_key(out)
    assert rows[world.m1]["name"] == "fake-model" and rows[world.m1]["sub"] == "fake-model"
    assert rows[world.m2]["name"] == "Model Hai" and rows[world.m2]["sub"] == "m2" and rows[world.m2]["requests"] == 3
    prices = rows[world.m1]["prices"]
    assert (Decimal(str(prices["input"])), Decimal(str(prices["output"]))) == (Decimal(3), Decimal(15))
    assert Decimal(str(prices["cache_read"])) == Decimal("0.3") and Decimal(str(prices["cache_write"])) == Decimal(
        "3.75"
    )
    ghost = next(r for r in out["rows"] if r["name"] == "ghost-model")  # tên lấy từ document, không có giá
    assert ghost["prices"] is None and ghost["sub"] == "ghost-model"
    assert [r["cost"] for r in out["rows"]] == sorted((r["cost"] for r in out["rows"]), reverse=True)

    rows = by_key(await api.get("usage.summary", root, group_by="agent"))
    assert rows[world.a1]["name"] == "Assistant" and rows[world.a1]["sub"] == "assistant"
    assert rows[world.a2]["name"] == "Agent Hai" and rows[world.a2]["requests"] == 3
    ghost_agent = next(r for r in rows.values() if r["sub"] == "ghost-agent")
    assert ghost_agent["name"] == "ghost-agent"

    out = await api.get("usage.summary", root, group_by="purpose")
    rows = by_key(out)
    assert set(rows) == {"agent", "router"} and rows["router"]["requests"] == 1 and rows["router"]["errors_rate"] == 1
    assert rows["agent"]["requests"] == 5 and rows["agent"]["name"] is None

    rows = by_key(await api.get("usage.summary", root, group_by="user"))
    assert (
        rows[world.ua.id]["name"] == "An"
        and rows[world.ua.id]["sub"] == "a@x.io"
        and rows[world.ua.id]["requests"] == 3
    )
    assert rows[world.ub.id]["name"] == "Bình" and rows[world.ub.id]["requests"] == 3

    rows = by_key(await api.get("usage.summary", root, group_by="key"))
    assert rows[world.c1]["name"] == "k1" and rows[world.c1]["sub"] == "sk-…1234"
    assert rows[world.cred2]["name"] == "key-hai" and rows[world.cred2]["requests"] == 2
    assert rows["none"]["requests"] == 2 and rows["none"]["name"] is None and rows["none"]["errors_server"] == 1

    rows = by_key(await api.get("usage.summary", root, group_by="session"))
    assert rows[world.s_a]["requests"] == 2 and rows[world.s_b]["requests"] == 3 and len(rows) == 3


async def test_summary_day_and_hour_buckets_in_app_timezone(world):
    api, root, tz = world.api, world.root, world.tz
    docs = list(world.docs.values())
    days = by_key(await api.get("usage.summary", root, group_by="day"))
    want = {}
    for d in docs:
        want[d["at"].astimezone(tz).strftime("%Y-%m-%d")] = want.get(d["at"].astimezone(tz).strftime("%Y-%m-%d"), 0) + 1
    assert {k: v["requests"] for k, v in days.items()} == want
    keys = [r["key"] for r in (await api.get("usage.summary", root, group_by="day"))["rows"]]
    assert keys == sorted(keys)  # theo thời gian, không theo chi phí
    hours = by_key(await api.get("usage.summary", root, group_by="hour"))
    want_h = {}
    for d in docs:
        k = d["at"].astimezone(tz).strftime("%Y-%m-%d %H:00")
        want_h[k] = want_h.get(k, 0) + 1
    assert {k: v["requests"] for k, v in hours.items()} == want_h
    assert all(len(k) == 16 and k.endswith(":00") for k in hours)


async def test_summary_filters_combine_with_group_by(world):
    api, root = world.api, world.root
    cases = {
        "agent_id": (world.a2, 3),
        "model_id": (world.m1, 2),
        "provider_id": (world.p, 5),
        "user_id": (world.ub.id, 3),
        "credential_id": (world.cred2, 2),
        "session_id": (world.s_a, 2),
        "purpose": ("router", 1),
    }
    for name, (value, count) in cases.items():
        out = await api.get("usage.summary", root, group_by="model", **{name: value})
        assert out["total"]["requests"] == count, name
        assert sum(r["requests"] for r in out["rows"]) == count, name
    both = await api.get("usage.summary", root, group_by="key", user_id=world.ub.id, purpose="agent")
    assert both["total"]["requests"] == 2 and set(by_key(both)) == {world.cred2, "none"}
    none = await api.get("usage.summary", root, user_id=str(uuid.uuid4()))
    assert none["rows"] == [] and none["total"] is None


async def test_summary_window_default_since_until_and_validation(world):
    api, root = world.api, world.root
    base = world.base
    narrow = await api.get(
        "usage.summary",
        root,
        since=(base - timedelta(hours=1)).isoformat(),
        until=(base + timedelta(hours=3)).isoformat(),
    )
    assert narrow["total"]["requests"] == 5  # bỏ `old_other` (2 ngày trước)
    assert narrow["since"] and narrow["until"] and narrow["total"]["errors"] == 2
    month = await api.get("usage.summary", root)
    d = datetime.fromisoformat(month["until"]) - datetime.fromisoformat(month["since"])
    assert d.days == 30 and month["total"]["requests"] == 6
    now = datetime.now(UTC)
    assert await api.err(
        "GET", "usage.summary", root, params={"since": now.isoformat(), "until": (now - timedelta(days=1)).isoformat()}
    ) == (422, 1002)
    assert await api.err("GET", "usage.summary", root, params={"since": now.isoformat(), "until": now.isoformat()}) == (
        422,
        1002,
    )
    long = {"since": (now - timedelta(days=401)).isoformat(), "until": now.isoformat()}
    assert await api.err("GET", "usage.summary", root, params=long) == (422, 1002)
    ok400 = {"since": (now - timedelta(days=400)).isoformat(), "until": now.isoformat()}
    assert (await api.get("usage.summary", root, **ok400))["total"]["requests"] == 6
    assert await api.err("GET", "usage.summary", root, params={"group_by": "nope"}) == (422, 1002)
    out = await api.get(
        "usage.summary",
        root,
        since=(now - timedelta(days=60)).isoformat(),
        until=(now - timedelta(days=40)).isoformat(),
    )
    assert out["rows"] == [] and out["total"] is None


async def test_usage_ops_are_superadmin_only(world):
    admin = await world.api.as_user("adm@x.io", roles=("admin",))
    assert await world.api.err("GET", "usage.summary", admin) == (403, 1005)
    assert await world.api.err("GET", "usage.errors", admin) == (403, 1005)


async def test_errors_list_kind_paging_and_labels(world):
    api, root = world.api, world.root
    out = await api.get("usage.errors", root)
    assert out["enabled"] and out["total"] == 3 and out["limit"] == 20 and out["offset"] == 0
    assert [i["kind"] for i in out["items"]] == ["server", "rate", "other"]  # mới nhất trước
    server, rate, other = out["items"]
    assert rate["purpose"] == "router" and rate["agent"] == "Agent Hai" and rate["model"] == "Model Hai"
    assert rate["model_code"] == "m2" and rate["user"] == "Bình" and rate["key"] == "key-hai"
    assert (
        rate["provider_kind"] == "openai_compatible" and rate["latency_ms"] == 50 and rate["error"] == "429 Rate limit"
    )
    assert rate["run_id"] == world.docs["router_rate"]["run_id"] and rate["id"] == world.docs["router_rate"]["id"]
    assert server["key"] is None and other["agent"] == "Assistant" and other["user"] == "An"
    for kind, n in (("rate", 1), ("auth", 0), ("server", 1), ("other", 1)):
        got = await api.get("usage.errors", root, kind=kind)
        assert got["total"] == n and all(i["kind"] == kind for i in got["items"]), kind
    page = await api.get("usage.errors", root, limit=1, offset=1)
    assert page["total"] == 3 and [i["kind"] for i in page["items"]] == ["rate"] and page["limit"] == 1
    assert (await api.get("usage.errors", root, user_id=world.ua.id))["total"] == 1
    assert (await api.get("usage.errors", root, purpose="router"))["total"] == 1
    assert await api.err("GET", "usage.errors", root, params={"limit": 101}) == (422, 1002)
    assert await api.err("GET", "usage.errors", root, params={"kind": "zzz"}) == (422, 1002)


async def test_disabled_when_mongo_off(stack):  # noqa: F811
    if stack.mongo:
        pytest.skip("cần Mongo tắt")
    root = (await setup(stack.api, stack.llm_url)).root
    summary = await stack.api.get("usage.summary", root, group_by="day")
    errors = await stack.api.get("usage.errors", root)
    assert summary["enabled"] is False and summary["rows"] == [] and summary["total"] is None
    assert errors["enabled"] is False and errors["items"] == [] and errors["total"] == 0


async def test_summary_by_tenant_and_tenant_filter(world):
    """Chi phí AI theo từng khách hàng (D22): gộp `tenant` (nhãn = tên tổ chức), lọc `tenant_id`; document cũ không có
    tenant gộp vào "none"."""
    async with get_connections().postgres.rw() as s:
        acme = await make_tenant(s, "Acme")
    at = world.base + timedelta(hours=3)
    await put_calls(
        call_doc(at=at, tenant_id=str(DEFAULT_TENANT_ID), user_id=world.ua.id, cost=1.0, input_tokens=5),
        call_doc(at=at, tenant_id=str(acme.id), user_id=world.ub.id, cost=2.0, input_tokens=7),
        call_doc(at=at, tenant_id=str(acme.id), user_id=world.ub.id, cost=2.0, input_tokens=7),
    )
    rows = by_key(await world.api.get("usage.summary", world.root, group_by="tenant"))
    mine = rows[str(acme.id)]
    assert (mine["name"], mine["sub"], mine["requests"], mine["cost"]) == ("Acme", "acme", 2, 4.0)
    assert rows[str(DEFAULT_TENANT_ID)]["requests"] == 1
    assert rows["none"]["requests"] == len(world.docs)  # document cũ chưa có tenant_id
    only = await world.api.get("usage.summary", world.root, group_by="user", tenant_id=str(acme.id))
    assert [r["key"] for r in only["rows"]] == [world.ub.id] and only["total"]["requests"] == 2
