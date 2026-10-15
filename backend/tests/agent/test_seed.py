"""Seed agent: bước sau migrate idempotent + `scripts/seed_agent.py` (từ chối DB thật, gắn provider / model / key)."""

import importlib.util
import json
from pathlib import Path

import pytest
from sqlmodel import select

from app.agent.config import seed
from app.agent.config.models import Agent, AgentKey, AgentModel, AgentProvider, AgentSystemPrompt, AgentToolset
from app.agent.config.seed_data import specialists
from app.core.connections.registry import get_connections
from app.credentials import crypto
from app.credentials.models import Credential
from app.credentials.service import reveal

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "seed_agent.py"


def load_script():
    spec = importlib.util.spec_from_file_location("seed_agent_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_seed_creates_assistant_and_persona_once(app_env):
    async with get_connections().postgres.rw() as s:
        agent = (await s.exec(select(Agent).where(Agent.slug == "assistant"))).one()
        persona = await s.get(AgentSystemPrompt, "persona")
        sets = set((await s.exec(select(AgentToolset.toolset).where(AgentToolset.agent_id == agent.id))).all())
        assert (
            agent.name == "Assistant"
            and agent.kind == "orchestrator"
            and agent.model_id is None
            and agent.visible_to == "all"
        )
        assert not sets and persona.content and agent.instructions and agent.starters
        agent.instructions, persona.content = "TUỲ CHỈNH", "PERSONA SỬA"
        s.add_all([agent, persona])
    async with get_connections().postgres.rw() as s:
        assert await seed.seed_agents(s) == {
            "persona": False,
            "assistant": None,
            "specialists": [],
            "routes": 0,
            "upgraded": [],
        }
    async with get_connections().postgres.ro() as s:
        assert (await s.exec(select(Agent).where(Agent.slug == "assistant"))).one().instructions == "TUỲ CHỈNH"
        assert (await s.get(AgentSystemPrompt, "persona")).content == "PERSONA SỬA"
        assert len((await s.exec(select(Agent))).all()) == 1 + len(specialists())  # assistant + chuyên gia nền + module


async def test_seed_recreates_missing_pieces(app_env):
    async with get_connections().postgres.rw() as s:
        await s.delete(await s.get(AgentSystemPrompt, "persona"))
        await s.delete((await s.exec(select(Agent).where(Agent.slug == "assistant"))).one())
    async with get_connections().postgres.rw() as s:
        made = await seed.seed_step(s, app_env)
        assert made["persona"] is True and made["assistant"] == "created" and made["routes"] == len(specialists())


def test_prompts_are_present():
    for name in ("persona", "router", "_common", "general"):
        assert len(seed.prompt(name)) > 100


async def test_seed_agent_script_refuses_real_db(app_env, monkeypatch):
    script = load_script()
    real = app_env.model_copy(update={"POSTGRES_RW_URL": app_env.POSTGRES_RW_URL.rsplit("/", 1)[0] + "/bizwithagents"})
    monkeypatch.setattr(script, "get_settings", lambda: real)
    opts = script.parse(["--provider", "openai_compatible", "--model", "m", "--key", "fake-key"])
    with pytest.raises(SystemExit) as exc:
        await script.run(opts)
    assert "từ chối" in str(exc.value)
    prod = app_env.model_copy(update={"ENV": "prod"})
    monkeypatch.setattr(script, "get_settings", lambda: prod)
    with pytest.raises(SystemExit):
        await script.run(opts)


def test_seed_agent_script_needs_key():
    script = load_script()
    with pytest.raises(SystemExit):
        script.parse(["--provider", "openai", "--model", "m"])


async def test_seed_agent_script_attaches_provider_model_key_to_default_agents(app_env, monkeypatch, tmp_path, capsys):
    app_env.CREDENTIAL_KEYS = crypto.new_key()
    script = load_script()
    monkeypatch.setattr(script, "get_settings", lambda: app_env)
    keyfile = tmp_path / "k.txt"
    keyfile.write_text("sk-from-file-1234\n", encoding="utf-8")
    args = [
        "--provider",
        "openai_compatible",
        "--base-url",
        "http://127.0.0.1:1/v1",
        "--model",
        "fake-model",
        "--input-price",
        "1.5",
    ]
    out = await script.run(script.parse([*args, "--key", "fake-key"]))
    assert (
        out["agents"] == 1 + len(specialists())
        and out["provider"] == "openai_compatible"
        and out["model"] == "fake-model"
    )
    out2 = await script.run(script.parse([*args, "--key-file", str(keyfile)]))  # chạy lại: cập nhật, không nhân đôi
    assert out2["credential"] == "sk-…1234"
    async with get_connections().postgres.ro() as s:
        assert (
            len((await s.exec(select(AgentProvider))).all()) == 1 and len((await s.exec(select(Credential))).all()) == 1
        )
        model = (await s.exec(select(AgentModel))).one()
        agents = (await s.exec(select(Agent))).all()
        keys = (await s.exec(select(AgentKey))).all()
        assert (
            len(agents) == 1 + len(specialists())
            and {a.model_id for a in agents} == {model.id}
            and float(model.input_price_per_1m) == 1.5
        )
        key = keys[0]
        assert await reveal(s, key.credential_id, app_env, purpose="test") == "sk-from-file-1234"


def test_seed_agent_script_main_prints_json(monkeypatch, capsys):
    script = load_script()

    async def fake_run(opts):
        return {"model": opts.model}

    monkeypatch.setattr(script, "run", fake_run)
    monkeypatch.setattr(script.sys, "argv", ["seed_agent.py", "--provider", "openai", "--model", "m1", "--key", "k"])
    assert script.main() == 0
    assert json.loads(capsys.readouterr().out) == {"model": "m1"}
