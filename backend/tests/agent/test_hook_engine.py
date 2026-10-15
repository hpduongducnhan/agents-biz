"""Engine hook: thứ tự `position`, `block` đầu tiên thắng, hành động theo điểm móc, dry-run, hook hỏng không lan."""

import uuid
from types import SimpleNamespace

import pytest

from app.agent.hooks import engine, webhook
from app.agent.hooks.engine import HookOutcome
from tests.agent.helpers import get_root, notes

DATA = {
    "user": {"id": None, "name": "An"},
    "agent": {"slug": "assistant"},
    "args": {"amount": 2_000_000},
    "tool": {"operation": "notifications.list"},
}


def hook(point, action, conditions=(), *, position=0, enabled=True, name="h", config=None):
    return SimpleNamespace(
        id=uuid.uuid4(), point=point, action=action["action"], action_config=config if config is not None else action,
        conditions=list(conditions), position=position, enabled=enabled, name=name,
    )  # fmt: skip


BLOCK = {"action": "block", "message": "Chặn {{user.name}}"}
GT = {"path": "args.amount", "op": "gt", "value": 1_000_000}


class Spy:
    def __init__(self):
        self.calls = []

    def hook(self, h, point, result, *, parent=None, error=None):
        self.calls.append((h.name, point, result, error))


async def test_before_tool_amount_gt_requires_approval():
    hooks = [hook("before_tool", {"action": "require_approval"}, [GT])]
    out = await engine.run("before_tool", hooks, DATA)
    assert out.approval and not out.blocked and out.results[0]["action"] == "require_approval"
    small = {**DATA, "args": {"amount": 5}}
    assert (await engine.run("before_tool", hooks, small)).approval is False


async def test_block_first_wins_and_stops_later_hooks(aenv):
    hooks = [
        hook("before_run", {"action": "add_context", "text": "sau"}, position=5, name="late"),
        hook("before_run", BLOCK, position=1, name="blocker"),
        hook("before_run", {"action": "block", "message": "thứ hai"}, position=2, name="second"),
        hook("before_run", {"action": "add_context", "text": "trước"}, position=0, name="early"),
    ]
    spy = Spy()
    out = await engine.run("before_run", hooks, DATA, tracer=spy)
    assert out.blocked and out.message == "Chặn An" and out.context == ["trước"]
    assert [c[0] for c in spy.calls] == ["early", "blocker"]  # dừng sau block, hook trễ không chạy


async def test_point_enabled_and_allowed_action_filters():
    hooks = [
        hook("before_tool", BLOCK),
        hook("before_run", BLOCK, enabled=False),
        hook("after_run", BLOCK),  # block không được phép ở after_run → bỏ qua
        hook("before_run", {"action": "add_context", "text": "ok"}, [{"path": "args.amount", "op": "lt", "value": 1}]),
    ]
    out = await engine.run("before_run", hooks, DATA)
    assert not out.blocked and out.results == [] and out.context == []
    assert (await engine.run("after_run", hooks, DATA)).results == []


async def test_add_context_collects_rendered_texts():
    hooks = [
        hook("before_run", {"action": "add_context", "text": f"ngữ cảnh {i} cho {{{{user.name}}}}"}, position=i)
        for i in range(2)
    ]
    assert (await engine.run("before_run", hooks, DATA)).context == ["ngữ cảnh 0 cho An", "ngữ cảnh 1 cho An"]


async def test_notify_sends_to_user_and_superadmins_but_not_in_dry_run(api, aenv):
    root = await get_root(api)
    u = await api.as_user("u@x.io")
    data = {**DATA, "user": {"id": u.id, "name": "An"}}
    to_user = hook("after_run", {"action": "notify", "to": "user", "text": "Xong {{user.name}}"})
    to_sup = hook("after_run", {"action": "notify", "to": "superadmins", "text": "Báo admin"})
    dry = await engine.run("after_run", [to_user, to_sup], data, dry=True)
    assert [r["sent"] for r in dry.results] == [False, False] and await notes(u.id) == [] and await notes(root.id) == []
    real = await engine.run("after_run", [to_user, to_sup], data)
    assert [r["sent"] for r in real.results] == [True, True]
    (mine,) = await notes(u.id, "agent_hook")
    assert mine.title == "Xong An" and (await notes(root.id, "agent_hook"))[0].title == "Báo admin"
    nobody = await engine.run("after_run", [hook("after_run", {"action": "notify", "to": "user", "text": "x"})], DATA)
    assert nobody.results[0]["user_id"] is None


async def test_webhook_queued_or_dry_request(api, aenv, monkeypatch):
    sent = []

    async def kiq(*args):
        sent.append(args)

    monkeypatch.setattr(webhook.send_webhook, "kiq", kiq)
    h = hook("after_run", {"action": "webhook", "url": "https://hook.test/x?a=1"})
    run_id = uuid.uuid4()
    out = await engine.run("after_run", [h], DATA, run_id=run_id)
    assert out.results[0]["queued"] and out.results[0]["url"] == "https://hook.test/x?a=1"
    (args,) = sent
    assert args[0] == str(h.id) and args[1] == "https://hook.test/x?a=1" and args[4] == str(run_id)
    assert (
        args[2]["point"] == "after_run"
        and args[2]["agent"] == "assistant"
        and args[2]["data"] == DATA
        and args[3] is None
    )
    dry = await engine.run("after_run", [h], DATA, dry=True)
    assert dry.results[0]["sent"] is False and dry.results[0]["request"]["url"] == "https://hook.test/x?a=1"
    assert "X-BizWithAgents-Signature" not in dry.results[0]["request"]["headers"] and len(sent) == 1


async def test_broken_hook_is_recorded_not_raised(bw_log):
    bad = hook("before_run", BLOCK, name="hỏng", config={"action": "explode"})
    good = hook("before_run", {"action": "add_context", "text": "vẫn chạy"}, position=1, name="tốt")
    spy = Spy()
    out = await engine.run("before_run", [bad, good], DATA, tracer=spy)
    assert out.context == ["vẫn chạy"] and "error" in out.results[0] and not out.blocked
    assert spy.calls[0][3] and spy.calls[1][3] is None
    assert any(r.get("loc") == "agt0704" for r in bw_log())


def test_outcome_defaults():
    out = HookOutcome()
    assert (out.blocked, out.message, out.approval, out.context, out.results) == (False, None, False, [], [])
    assert pytest
