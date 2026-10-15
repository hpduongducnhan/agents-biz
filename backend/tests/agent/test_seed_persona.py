"""Seed nâng persona chung: bản seed cũ được nâng một lần, bản sửa tay giữ nguyên và ghi log `agt0007`."""

import hashlib
import logging

from app.agent.config import seed
from app.agent.config.models import AgentSystemPrompt
from app.agent.config.seed_data import PREVIOUS_PERSONA
from app.core.connections.registry import get_connections

OLD_TEXT = "persona cũ của trợ lý\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


async def run_seed() -> dict:
    async with get_connections().postgres.rw() as s:
        return await seed.seed_agents(s)


async def persona() -> str:
    async with get_connections().postgres.ro() as s:
        return (await s.get(AgentSystemPrompt, "persona")).content


async def set_persona(text: str) -> None:
    async with get_connections().postgres.rw() as s:
        row = await s.get(AgentSystemPrompt, "persona")
        row.content = text
        s.add(row)


def test_previous_persona_hash_registered_and_new_not():
    assert isinstance(PREVIOUS_PERSONA, frozenset)
    assert sha(seed.prompt("persona")) not in PREVIOUS_PERSONA


async def test_old_persona_is_upgraded_once(app_env, monkeypatch):
    monkeypatch.setattr(seed, "PREVIOUS_PERSONA", frozenset({sha(OLD_TEXT)}))
    await set_persona(OLD_TEXT)
    made = await run_seed()
    assert "persona" in made["upgraded"]
    assert await persona() == seed.prompt("persona")
    again = await run_seed()
    assert "persona" not in again["upgraded"] and await persona() == seed.prompt("persona")


async def test_hand_edited_persona_is_kept_and_logged(app_env, monkeypatch, caplog):
    monkeypatch.setattr(seed, "PREVIOUS_PERSONA", frozenset({sha(OLD_TEXT)}))
    await set_persona(OLD_TEXT + "thêm luật riêng")
    with caplog.at_level(logging.INFO):
        made = await run_seed()
    assert "persona" not in made["upgraded"] and await persona() == OLD_TEXT + "thêm luật riêng"
    assert any(getattr(r, "loc", None) == "agt0007" for r in caplog.records)


async def test_current_persona_is_untouched(app_env, caplog):
    await set_persona(seed.prompt("persona"))
    with caplog.at_level(logging.INFO):
        made = await run_seed()
    assert "persona" not in made["upgraded"] and await persona() == seed.prompt("persona")
    assert not any(getattr(r, "loc", None) == "agt0007" for r in caplog.records)
