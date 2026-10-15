"""Stream chat (D23): cài đặt đọc đầu mỗi đoạn chạy; lỗi đọc → mặc định + WARNING agt0509; model theo `stream`."""

import logging
from types import SimpleNamespace

import pytest

from app.agent.runtime import llm, streaming
from app.agent.runtime.streaming import StreamCfg, load_stream_cfg
from app.system.settings_store import SystemSettings


def spec(kind):
    provider = SimpleNamespace(kind=kind, base_url="http://x.test/v1", extra_headers={}, default_params={}, name=kind)
    model = SimpleNamespace(model_id="m-x")
    return SimpleNamespace(provider=provider, model=model, agent=SimpleNamespace(params_override={}))


async def test_load_stream_cfg_reads_configured_values(monkeypatch):
    async def fake():
        return SystemSettings(chat_stream=False, chat_stream_flush_ms=300)

    monkeypatch.setattr(streaming, "cached_system_settings", fake)
    cfg = await load_stream_cfg()
    assert cfg == StreamCfg(on=False, flush_ms=300, defaults_applied=())
    assert cfg.window == 0.3 and cfg.trace() == {"on": False, "flush_ms": 300, "defaults_applied": []}


async def test_load_stream_cfg_failure_uses_defaults_and_warns_once(monkeypatch, caplog):
    async def boom():
        raise ConnectionError("redis chết")

    monkeypatch.setattr(streaming, "cached_system_settings", boom)
    with caplog.at_level(logging.WARNING, logger="bw"):
        cfg = await load_stream_cfg()
    assert (cfg.on, cfg.flush_ms) == (True, 50) and cfg.defaults_applied == ("chat_stream", "chat_stream_flush_ms")
    hits = [r for r in caplog.records if getattr(r, "loc", "") == "agt0509"]
    assert len(hits) == 1 and hits[0].levelno == logging.WARNING and "DEFAULTS_APPLIED" in hits[0].getMessage()
    assert cfg.trace()["defaults_applied"] == ["chat_stream", "chat_stream_flush_ms"]


@pytest.mark.parametrize("kind", ["openai", "openai_compatible"])
def test_openai_kinds_stream_off(kind):
    off = llm.build_chat_model(spec(kind), api_key="k", stream=False)
    assert off.streaming is False and off.disable_streaming is True
    on = llm.build_chat_model(spec(kind), api_key="k")
    assert on.streaming is True and on.stream_usage is True and not on.disable_streaming


def test_anthropic_stream_off():
    off = llm.build_chat_model(spec("anthropic"), api_key="sk-ant", stream=False)
    assert off.streaming is False and off.disable_streaming is True
    on = llm.build_chat_model(spec("anthropic"), api_key="sk-ant", stream=True)
    assert on.streaming is True and not on.disable_streaming


def test_google_stream_off_disables_streaming():
    off = llm.build_chat_model(spec("google_genai"), api_key="AIza", stream=False)
    assert off.disable_streaming is True
