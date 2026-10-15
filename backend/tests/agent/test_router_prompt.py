"""Prompt router: bảng route (mã — ý định — ví dụ), tin gần nhất, trạng thái, ngữ cảnh rút gọn (không số dư)."""

import uuid

import pytest

from app.agent.chat.models import AgentMessage
from app.agent.config.registry import RouteSpec
from app.agent.router import prompt
from app.agent.runtime import context
from app.core.connections.registry import get_connections
from tests.agent.helpers import setup

AID = uuid.uuid4()


def route(slug, name, intent, examples, pos=0):
    return RouteSpec(uuid.uuid4(), slug, name, intent, tuple(examples), pos)


def msg(role, text, agent_id=None, seq=1):
    return AgentMessage(session_id=AID, seq=seq, role=role, agent_id=agent_id, content={"text": text})


def test_prompt_lists_enabled_routes_with_examples_and_short_context():
    routes = (
        route("personal", "Sổ cá nhân", "Ghi thu chi", ["ăn trưa 45k", "lương 15tr", "a", "b", "c", "d-bị-cắt"]),
        route("report", "Báo cáo", "Xem tổng chi", []),
    )
    out = prompt.build(
        "HƯỚNG DẪN ROUTER ",
        routes,
        text="ăn trưa 45k",
        recent=["user: chào", "assistant(personal): ok"],
        last_agent="personal",
        asked_back=True,
        context="ví: Tiền mặt (VND, cash)\nnhóm: -",
    )
    system, human = out[0].content, out[1].content
    assert system.startswith("HƯỚNG DẪN ROUTER\n\n## Chuyên gia")
    assert "| `personal` | Sổ cá nhân | Ghi thu chi |" in system and '"ăn trưa 45k"' in system
    assert '"d-bị-cắt"' not in system  # tối đa 5 ví dụ mỗi route
    assert "| `report` | Báo cáo | Xem tổng chi |" in system
    assert "<recent>\nuser: chào\nassistant(personal): ok\n</recent>" in human
    assert "chuyên gia lượt trước: personal" in human and "kết thúc bằng câu hỏi lại: có" in human
    assert "Tiền mặt (VND, cash)" in human and human.rstrip().endswith("Tin nhắn mới: ăn trưa 45k")
    assert (
        "chuyên gia lượt trước: - · lượt trước kết thúc bằng câu hỏi lại: không"
        in prompt.build("x", routes, text="t", recent=[], last_agent=None, asked_back=False, context="")[1].content
    )


def test_recent_lines_skip_tools_cap_text_and_keep_last_six():
    sp = uuid.uuid4()
    past = [msg("user", f"u{i}", seq=i) for i in range(5)] + [
        msg("tool", "kq", sp),
        msg("assistant", "", sp),
        msg("assistant", "x" * 1000, sp),
        msg("assistant", "đây", uuid.uuid4()),
    ]
    lines = prompt.recent_lines(past, {sp: "personal"})
    assert len(lines) == prompt.RECENT == 6
    assert lines[-2] == f"assistant(personal): {'x' * prompt.TEXT_CAP}" and lines[-1] == "assistant(-): đây"
    assert all("kq" not in x for x in lines)


@pytest.fixture
async def env(api, aenv, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    return stack, await api.as_user("u@x.io")


async def test_short_context_delegates_to_router_providers_only(env, monkeypatch):
    stack, u = env
    monkeypatch.setattr(context, "_PROVIDERS", {})

    async def names(session, user):
        return ["- Nhãn A", "- Nhãn B"]

    async def secret(session, user):
        return ["- 123456 số liệu"]

    context.register_context("names", names, router=True)
    context.register_context("secret", secret)
    async with get_connections().postgres.ro() as s:
        out = await prompt.short_context(s, uuid.UUID(u.id))
        assert out == "- Nhãn A\n- Nhãn B" and "123" not in out
        assert await prompt.short_context(s, uuid.uuid4()) == "-"
