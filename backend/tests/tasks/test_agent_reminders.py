"""Tasks qua trợ lý (LLM giả) + cron nhắc hạn: tạo việc bằng chat ghi `source=agent` + `agent_run_id`; xoá qua chat phải
duyệt; tool không chạm việc của tổ chức khác; ngữ cảnh có "việc của tôi"; nhắc hạn mỗi mốc một lần, đúng người."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from app.agent.runtime import context
from app.core.connections.registry import get_connections
from app.tasks.models import Task
from app.tasks.tasks import remind_due
from tests.agent.helpers import approvals, chat, setup
from tests.tasks.helpers import create, notifications_of, world

pytestmark = pytest.mark.integration


def call(op: str, **args) -> str:
    return f"call:{op} {json.dumps(args, ensure_ascii=False)}"


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm):
    await setup(api, fake_llm.base_url)
    return await world(api)


async def task_row(task_id: str) -> Task:
    async with get_connections().postgres.ro() as s:
        return (await s.exec(select(Task).where(Task.id == uuid.UUID(task_id)))).one()


async def test_create_by_chat_is_marked_agent(env):
    sent, run = await chat(env.api, env.member, call("tasks_create", title="Gọi khách thứ Sáu", priority="high"))
    assert run.status == "done"
    (item,) = (await env.api.get("tasks.list", env.member))["items"]
    assert (item["title"], item["source"], item["created_by"]["name"]) == ("Gọi khách thứ Sáu", "agent", "Lan")
    assert (await task_row(item["id"])).agent_run_id == uuid.UUID(sent["run_id"])


async def test_delete_by_chat_waits_for_approval(env):
    t = await create(env.api, env.admin, title="Xoá thử")
    sent, run = await chat(env.api, env.admin, call("tasks_delete", task_id=t["id"]))
    assert run.status == "waiting_approval"
    (req,) = await approvals(sent["run_id"])
    assert req.operation == "tasks.delete"
    assert (await env.api.get("tasks.get", env.admin, task_id=t["id"]))["title"] == "Xoá thử"  # chưa xoá


async def test_tools_cannot_touch_other_tenant(env):
    t = await create(env.api, env.member, title="Của tổ chức default")
    _, run = await chat(env.api, env.other, call("tasks_set_status", task_id=t["id"], status="done"))
    assert run.status == "done"
    assert (await task_row(t["id"])).status == "todo"  # tool nhận 10001, không đổi gì


async def test_context_lists_my_open_tasks(env):
    due = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    t = await create(env.api, env.admin, title="Báo cáo quý", assignee_id=env.member.id, due_at=due)
    await create(env.api, env.other, title="Việc Acme", assignee_id=env.other.id)
    async with get_connections().postgres.ro() as s:
        text = await context.build(s, uuid.UUID(env.member.id))
    assert "tasks: tổ chức todo 1" in text
    assert f"- task {t['id']} · Báo cáo quý · todo · ưu tiên normal" in text and "QUÁ HẠN" in text
    assert "Việc Acme" not in text  # ngữ cảnh đọc trong tổ chức của người chat


async def test_due_reminders_once_per_mark_and_right_person(env):
    now = datetime.now(UTC)
    soon = await create(
        env.api, env.admin, title="Sắp hạn", assignee_id=env.member.id, due_at=(now + timedelta(hours=3)).isoformat()
    )
    late = await create(env.api, env.member, title="Trễ hạn", due_at=(now - timedelta(hours=3)).isoformat())
    await create(env.api, env.member, title="Còn xa", due_at=(now + timedelta(days=5)).isoformat())
    await create(env.api, env.member, title="Xong", status="done", due_at=(now - timedelta(days=1)).isoformat())
    acme = await create(env.api, env.other, title="Acme trễ", due_at=(now - timedelta(hours=1)).isoformat())
    first = await remind_due()
    assert first == {"checked": 3, "sent": 3}
    assert await remind_due() == {"checked": 3, "sent": 0}  # chạy lại không nhắc trùng
    to_member = sorted((n.kind, n.params["title"]) for n in await notifications_of(env.member.id))
    assert to_member == [("task_assigned", "Sắp hạn"), ("task_due_soon", "Sắp hạn"), ("task_overdue", "Trễ hạn")]
    assert [n.kind for n in await notifications_of(env.other.id)] == ["task_overdue"]
    await env.api.post("tasks.update", env.member, task_id=late["id"], due_at=(now - timedelta(hours=2)).isoformat())
    assert (await remind_due())["sent"] == 1  # đổi hạn = mốc mới
    assert soon["id"] and acme["id"]
