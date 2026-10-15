"""Duyệt hàng loạt: `agent.decide_approvals`, khoá dòng run cho `decide_approval`, tool song song của LLM giả."""

import asyncio
import uuid

import pytest

from app.agent.runtime import runner
from app.agent.testing import fake_llm as fl
from tests.agent.helpers import add_notes, approvals, chat, get_root, run_row, setup, unread
from tests.auth.api import op_path

MARK = "call:notifications_mark_all_read {}"


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm, confirm_write):
    """Một run đang chờ 2 yêu cầu duyệt (2 lần đánh dấu đã đọc song song, 4 thông báo chưa đọc)."""
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    await add_notes(u.id, 4)
    assert await unread(api, u) == 4
    script = f"parallel đọc hết hai lần\n{MARK}\n{MARK}"
    sent, run = await chat(api, u, script)
    assert run.status == "waiting_approval"
    reqs = sorted(await approvals(sent["run_id"]), key=lambda a: str(a.id))
    assert len(reqs) == 2 and {r.status for r in reqs} == {"pending"}
    kicks.reset_mock()
    return api, u, sent["run_id"], [str(r.id) for r in reqs], kicks, script


def many(run_id: str, ids: list[str], approve: bool = True, reason: str | None = None) -> dict:
    return {"run_id": run_id, "approval_ids": ids, "approve": approve, "reason": reason}


async def statuses(run_id: str) -> dict[str, str]:
    return {str(a.id): a.status for a in await approvals(run_id)}


async def test_approve_all_resumes_once_and_runs_both_tools(env):
    api, u, run_id, ids, kicks, _ = env
    out = await api.post("agent.decide_approvals", u, **many(run_id, ids))
    assert out["resumed"] is True and out["skipped"] == [] and out["run_id"] == run_id
    assert {d["approval_id"]: d["status"] for d in out["decided"]} == {i: "approved" for i in ids}
    kicks.assert_awaited_once_with(run_id)
    assert await statuses(run_id) == {i: "approved" for i in ids}
    assert await runner.resume(run_id) is False
    assert (await run_row(run_id)).status == "done"
    assert await unread(api, u) == 0  # đã chạy


async def test_reject_all_with_reason_is_reported_to_llm(env):
    api, u, run_id, ids, kicks, _ = env
    out = await api.post("agent.decide_approvals", u, **many(run_id, ids, False, "để lại"))
    assert out["resumed"] is True and {d["status"] for d in out["decided"]} == {"rejected"}
    kicks.assert_awaited_once_with(run_id)
    assert {a.reason for a in await approvals(run_id)} == {"để lại"}
    await runner.resume(run_id)
    assert (await run_row(run_id)).status == "done"
    assert await unread(api, u) == 4
    tool_msgs = [m for m in fl.REQUESTS[-1]["body"]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 2 and all("từ chối" in m["content"] for m in tool_msgs)


async def test_mixed_one_already_decided_is_skipped(env):
    api, u, run_id, ids, kicks, _ = env
    await api.post("agent.decide_approval", u, approval_id=ids[0], approve=True)
    kicks.assert_not_awaited()
    out = await api.post("agent.decide_approvals", u, **many(run_id, ids))
    assert [d["approval_id"] for d in out["decided"]] == [ids[1]] and out["skipped"] == [ids[0]]
    assert out["resumed"] is True
    kicks.assert_awaited_once_with(run_id)


async def test_all_ids_already_decided_is_409_with_skipped(env):
    api, u, run_id, ids, kicks, _ = env
    await api.post("agent.decide_approvals", u, **many(run_id, ids))
    kicks.reset_mock()
    r = await api.call("POST", op_path("agent.decide_approvals"), u, json=many(run_id, ids))
    assert r.status_code == 409 and r.json()["code"] == 6008
    assert sorted(r.json()["data"]["skipped"]) == sorted(ids)
    kicks.assert_not_awaited()


async def test_other_users_run_is_404_and_superadmin_allowed(env):
    api, u, run_id, ids, kicks, _ = env
    other = await api.as_user("o@x.io")
    assert await api.err("POST", "agent.decide_approvals", other, json=many(run_id, ids)) == (404, 6006)
    assert await statuses(run_id) == {i: "pending" for i in ids}
    root = await get_root(api)
    out = await api.post("agent.decide_approvals", root, **many(run_id, ids))
    assert out["resumed"] is True and len(out["decided"]) == 2
    kicks.assert_awaited_once_with(run_id)


async def test_partial_set_does_not_resume_until_last(env):
    api, u, run_id, ids, kicks, _ = env
    out = await api.post("agent.decide_approvals", u, **many(run_id, ids[:1]))
    assert out["resumed"] is False and len(out["decided"]) == 1
    kicks.assert_not_awaited()
    out = await api.post("agent.decide_approvals", u, **many(run_id, ids[1:]))
    assert out["resumed"] is True
    kicks.assert_awaited_once_with(run_id)


async def test_id_from_other_run_skipped_and_duplicates_deduped(env):
    api, u, run_id, ids, kicks, script = env
    sent2, _ = await chat(api, u, f"đọc hết\n{MARK}", session_id=None)
    foreign = [str(a.id) for a in await approvals(sent2["run_id"])]
    stranger = str(uuid.uuid4())
    out = await api.post("agent.decide_approvals", u, **many(run_id, [ids[0], ids[0], *foreign, stranger]))
    assert [d["approval_id"] for d in out["decided"]] == [ids[0]]
    assert out["skipped"] == [*foreign, stranger] and out["resumed"] is False
    assert await statuses(sent2["run_id"]) == {f: "pending" for f in foreign}


async def test_validation_rejects_empty_and_too_many(env):
    api, u, run_id, ids, _, _ = env
    assert await api.err("POST", "agent.decide_approvals", u, json=many(run_id, [])) == (422, 1002)
    too_many = [str(uuid.uuid4()) for _ in range(51)]
    assert await api.err("POST", "agent.decide_approvals", u, json=many(run_id, too_many)) == (422, 1002)


async def test_two_concurrent_single_decisions_resume_exactly_once(env):
    api, u, run_id, ids, kicks, _ = env
    await asyncio.gather(*(api.post("agent.decide_approval", u, approval_id=i, approve=True) for i in ids))
    kicks.assert_awaited_once_with(run_id)
    assert await statuses(run_id) == {i: "approved" for i in ids}
    await runner.resume(run_id)
    assert await unread(api, u) == 0


async def test_concurrent_batch_and_single_resume_exactly_once(env):
    api, u, run_id, ids, kicks, _ = env
    single, batch = await asyncio.gather(
        api.post("agent.decide_approval", u, approval_id=ids[0], approve=True),
        api.post("agent.decide_approvals", u, **many(run_id, ids)),
        return_exceptions=True,
    )
    # gom chạy trước → lệnh lẻ gặp 409/6008; lẻ chạy trước → gom bỏ qua id đã quyết (không bao giờ cả hai lỗi)
    assert not isinstance(batch, Exception)
    if isinstance(single, Exception):
        assert "6008" in str(single)
    kicks.assert_awaited_once_with(run_id)
    assert await statuses(run_id) == {i: "approved" for i in ids}
