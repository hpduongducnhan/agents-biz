"""Fixture dùng chung cho test agent + credentials (nạp qua conftest của hai thư mục)."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from langchain_openai.chat_models import _client_utils

import app.agent.ops  # noqa: F401 — nạp op agent / studio
import app.agent.tasks as agent_tasks
from app.agent.config import registry, seed_data, toolsets
from app.agent.config.seed_data import SpecialistSeed, register_specialist
from app.agent.runtime import checkpoint
from app.agent.testing import fake_llm as fake_llm_mod
from app.agent.testing.fake_llm import FakeLLMServer
from app.credentials import crypto
from tests.agent import sinks


@pytest.fixture(scope="session")
def fake_llm_server():
    server = FakeLLMServer().start()
    yield server
    server.stop()


@pytest.fixture
def fake_llm(fake_llm_server):
    fake_llm_mod.REQUESTS.clear()
    fake_llm_mod.HOOK_CALLS.clear()
    fake_llm_mod.PARALLEL = False
    return fake_llm_server


@pytest.fixture
async def aenv(app_env, rt, monkeypatch, fake_llm):
    """app_env + khoá credential tạm + cache registry / checkpointer sạch + kiq giả."""
    monkeypatch.setattr(app_env, "CREDENTIAL_KEYS", crypto.new_key())
    registry._cache.clear()
    checkpoint.reset()
    # client httpx dùng chung bị buộc vào event loop của test trước
    _client_utils._cached_async_httpx_client.cache_clear()
    kicks = AsyncMock()
    monkeypatch.setattr(agent_tasks.run_turn, "kiq", kicks)
    monkeypatch.setattr(agent_tasks.resume_turn, "kiq", kicks)
    yield app_env
    _client_utils._cached_async_httpx_client.cache_clear()
    checkpoint.reset()
    registry._cache.clear()


@pytest.fixture
def kicks(aenv):
    return agent_tasks.run_turn.kiq


@pytest.fixture
def trace_sink():
    """Sink trace trong bộ nhớ gắn vào `get_sinks().traces` (Mongo bật giả); xong test đặt lại Noop."""
    sink = sinks.MemoryTraceSink()
    sinks.install(sink)
    yield sink
    sinks.uninstall()


@pytest.fixture
def confirm_write(monkeypatch):
    """`notifications.mark_all_read` thành thao tác cần duyệt (nền tảng không khai sẵn thao tác nào cần duyệt)."""
    lookup = replace(toolsets._TOOLSETS["lookup"], confirm_writes=frozenset({"notifications.mark_all_read"}))
    monkeypatch.setitem(toolsets._TOOLSETS, "lookup", lookup)


TEAM = (
    ("personal", "Cá nhân", "Việc riêng của người dùng", "Personal tasks", ("việc của tôi", "my tasks")),
    ("report", "Báo cáo", "Tổng hợp, báo cáo", "Summaries and reports", ("xem tổng", "show summary")),
)


@pytest.fixture
def team(tmp_path):
    """Đội chuyên gia thử của nền: `personal`, `report` + `general` — đăng ký TRƯỚC khi test dựng DB (đặt trước `api` /
    `aenv`). Chuyên gia của module (vd `tasks`) tạm gỡ để test router / handoff chỉ thấy đội này; xong trả lại."""
    before = dict(seed_data._SEEDS)
    seed_data._SEEDS.clear()
    seed_data._SEEDS["general"] = before["general"]
    for slug, name, desc, intent, examples in TEAM:
        prompt = f"Bạn là chuyên gia {name}. Dùng tool tra cứu khi cần.\n"
        (tmp_path / f"{slug}.md").write_text(prompt, encoding="utf-8")
        register_specialist(SpecialistSeed(slug, name, desc, ("lookup",), intent, examples, prompt_dir=tmp_path))
    yield [slug for slug, *_ in TEAM]
    seed_data._SEEDS.clear()
    seed_data._SEEDS.update(before)
