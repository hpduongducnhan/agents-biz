"""`handoff(to, reason)`: chèn bước đích sau bước hiện tại, ≤ 2 lần / lượt; hết lượt → không có tool `handoff`."""

import json

import pytest

from app.agent.runtime.plan import MAX_HANDOFFS
from app.agent.runtime.tools import HandoffState, RunContext, build_tools, make_handoff
from app.agent.testing import fake_llm as fl
from tests.agent.helpers import chat, events_of, load_spec, make_rc, messages, setup, setup_router, slug_ids


@pytest.fixture
async def env(team, api, aenv, rt, kicks, fake_llm):
    stack = await setup_router(api, fake_llm.base_url)
    return stack, await api.as_user("u@x.io"), rt


def hand(to: str, reason: str) -> str:
    return "call:handoff " + json.dumps({"to": to, "reason": reason}, ensure_ascii=False)


def tool_names(req) -> set[str]:
    return {t["function"]["name"] for t in req["body"].get("tools") or []}


async def test_handoff_tool_offered_to_specialists_with_other_targets_only(env):
    stack, u, _ = env
    fl.REQUESTS.clear()
    await chat(stack.api, u, "route:personal việc")
    (req,) = [r for r in fl.REQUESTS if "handoff" in tool_names(r)]
    schema = next(t["function"] for t in req["body"]["tools"] if t["function"]["name"] == "handoff")
    enum = schema["parameters"]["properties"]["to"]["enum"]
    assert enum == ["general", "report"]  # không có chính nó
    assert schema["parameters"]["required"] == ["to"]


async def test_handoff_inserts_next_step_after_current(env):
    stack, u, rt = env
    sent, run = await chat(stack.api, u, "route:personal " + hand("report", "xem tổng chi"))
    assert run.status == "done" and run.plan["handoffs"] == 1 and run.plan["cursor"] == 2
    assert [(s["slug"], s["via"]) for s in run.plan["steps"]] == [("personal", "router"), ("report", "handoff")]
    assert run.plan["steps"][1]["task"] == "xem tổng chi"
    ids = await slug_ids()
    rows = await messages(sent["session_id"])
    by_agent = [(m.role, m.agent_id) for m in rows[1:]]
    assert by_agent[0] == ("assistant", ids["personal"]) and by_agent[1] == ("tool", ids["personal"])
    tool = rows[2].content
    assert tool["name"] == "handoff" and tool["text"] == "Đã chuyển cho Báo cáo: xem tổng chi"
    assert by_agent[-1] == ("assistant", ids["report"])  # bước chèn trả lời
    bys = [d["by"]["slug"] for _, d in events_of(rt, u.id, "agent:token")[:-1]]
    assert "report" in bys and len(events_of(rt, u.id, "agent:end")) == 1


async def test_handoff_in_the_middle_of_three_steps_inserts_before_the_next(env):
    stack, u, _ = env
    _, run = await chat(stack.api, u, "route:personal,report " + hand("general", "chào") + " | tổng")
    assert [s["slug"] for s in run.plan["steps"]] == ["personal", "general", "report"] and run.plan["cursor"] == 3


async def test_handoff_caps_at_two_then_step_has_no_handoff_tool(env):
    stack, u, _ = env
    third = hand("personal", "lần ba")
    second = hand("report", third)
    fl.REQUESTS.clear()
    sent, run = await chat(stack.api, u, "route:personal " + hand("general", second))
    assert run.status == "done" and run.plan["handoffs"] == MAX_HANDOFFS == 2
    assert [s["slug"] for s in run.plan["steps"]] == ["personal", "general", "report"]
    tools = [tool_names(r) for r in fl.REQUESTS if "RouteDecision" not in tool_names(r)]
    assert len(tools) == 3 and "handoff" in tools[0] and "handoff" in tools[1] and "handoff" not in tools[2]
    rows = await messages(sent["session_id"])
    assert not [m for m in rows if m.role == "tool" and m.content.get("status") == "error"]  # không còn lỗi 6021
    assert rows[-1].role == "assistant" and rows[-1].content["text"]  # người dùng có câu trả lời


async def test_handoff_enum_excludes_came_from(env):
    stack, u, _ = env
    fl.REQUESTS.clear()
    _, run = await chat(stack.api, u, "route:personal " + hand("general", "chào"))
    assert [s["slug"] for s in run.plan["steps"]] == ["personal", "general"]
    enums = []
    for r in fl.REQUESTS:
        for t in r["body"].get("tools") or []:
            if t["function"]["name"] == "handoff":
                enums.append(t["function"]["parameters"]["properties"]["to"]["enum"])
    assert enums[0] == ["general", "report"]
    assert enums[1] == ["report"]  # đang ở general, vừa đến từ personal


def test_handoff_state_choices_and_single_other_target_is_came_from():
    targets = {"a": object(), "b": object(), "c": object()}
    assert HandoffState(targets=targets, left=2, current="a").choices == ["b", "c"]
    assert HandoffState(targets=targets, left=2, current="a", came_from="b").choices == ["c"]
    two = HandoffState(targets={"a": object(), "b": object()}, left=2, current="a", came_from="b")
    assert two.choices == []


async def test_no_handoff_tool_when_only_other_target_is_came_from(env):
    stack, u, _ = env
    rc = await make_rc(u, toolsets=["lookup"])
    targets = {r.slug: r for r in (await _orch_routes()).routes}
    pair = {k: targets[k] for k in ("general", "personal")}
    rc.handoff = HandoffState(targets=pair, left=2, current="general", came_from="personal")
    assert not any(t.name == "handoff" for t in build_tools(rc))
    rc.handoff = HandoffState(targets=pair, left=2, current="general")
    assert any(t.name == "handoff" for t in build_tools(rc))
    rc.handoff = HandoffState(targets=pair, left=0, current="general")
    assert not any(t.name == "handoff" for t in build_tools(rc))


async def test_handoff_to_unknown_or_self_is_tool_error(env):
    stack, u, _ = env
    for bad in ("nosuch", "personal"):
        sent, run = await chat(stack.api, u, "route:personal " + hand(bad, "x"))
        assert run.status == "done" and run.plan["handoffs"] == 0 and len(run.plan["steps"]) == 1
        tool = [m for m in await messages(sent["session_id"]) if m.role == "tool"][-1].content
        assert (
            tool["status"] == "error" and tool["text"].startswith("Lỗi 1002") and "không có chuyên gia" in tool["text"]
        )


async def test_handoff_tool_unit_and_not_built_without_targets(env):
    stack, u, _ = env
    rc = await make_rc(u, toolsets=["lookup"])
    assert not any(t.name == "handoff" for t in build_tools(rc))  # không có HandoffState → không có tool
    spec = await load_spec(rc.spec.id)
    targets = {r.slug: r for r in (await _orch_routes()).routes}
    one = RunContext(rc.run_id, rc.session_id, rc.user, rc.principal, spec)
    one.handoff = HandoffState(targets={"general": targets["general"]}, left=2, current="general")
    assert not any(t.name == "handoff" for t in build_tools(one))  # chỉ còn chính nó → không có đích
    state = HandoffState(targets=targets, left=1, current="personal")
    one.handoff = state
    tool = make_handoff(one)
    assert tool.return_direct is True
    out = await tool.coroutine(to="report", reason="  chia  ")
    assert out == "Đã chuyển cho Báo cáo: chia" and (state.to, state.reason) == ("report", "chia")
    out = await tool.coroutine(to="report")
    assert state.to == "report" and state.reason == ""


async def _orch_routes():
    ids = await slug_ids()
    return await load_spec(ids["assistant"])


async def test_specialist_entry_has_no_handoff_tool(api, aenv, rt, kicks, fake_llm):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    fl.REQUESTS.clear()
    await chat(api, u, "chào")
    assert all("handoff" not in tool_names(r) for r in fl.REQUESTS)
