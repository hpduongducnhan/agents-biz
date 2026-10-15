"""Dựng chat model theo loại provider: không thử lại ngầm, base_url / header / tham số từ cấu hình."""

import sys
from types import SimpleNamespace

import pytest

from app.agent.runtime import llm


def spec(kind, *, base_url=None, headers=None, params=None, override=None):
    provider = SimpleNamespace(
        kind=kind, base_url=base_url, extra_headers=headers or {}, default_params=params or {}, name=kind
    )
    model = SimpleNamespace(
        model_id={"openai": "gpt-x", "anthropic": "claude-x", "google_genai": "gemini-x"}.get(kind, "m")
    )
    return SimpleNamespace(provider=provider, model=model, agent=SimpleNamespace(params_override=override or {}))


def test_openai_compatible_uses_base_url_headers_and_params():
    m = llm.build_chat_model(
        spec(
            "openai_compatible",
            base_url="http://x.test/v1",
            headers={"X-A": "1"},
            params={"temperature": 0.1},
            override={"temperature": 0.2},
        ),
        api_key="k",
    )
    assert m.openai_api_base == "http://x.test/v1" and m.max_retries == 0 and m.temperature == 0.2
    assert m.default_headers == {"X-A": "1"} and m.streaming is True


def test_anthropic_and_google_models_build_with_zero_retries():
    a = llm.build_chat_model(spec("anthropic", headers={"X-B": "2"}), api_key="sk-ant")
    assert a.max_retries == 0 and a.model == "claude-x"
    g = llm.build_chat_model(spec("google_genai", headers={"X-C": "3"}), api_key="AIza")
    assert g.max_retries == 0 and g.model.endswith("gemini-x")
    plain = llm.build_chat_model(spec("openai"), api_key="sk")
    assert plain.model_name == "gpt-x"


@pytest.mark.parametrize(("kind", "want"), [("openai_compatible", "openai_compatible"), ("anthropic", "anthropic")])
def test_provider_kind(kind, want):
    assert llm.provider_kind(spec(kind)) == want
    assert llm.provider_kind(SimpleNamespace(provider=None)) == ""


def test_warm_providers_imports_every_provider_package_and_logs(bw_log):
    assert llm.warm_providers() == list(llm.PROVIDER_PACKAGES)
    assert all(name in sys.modules for name in llm.PROVIDER_PACKAGES)
    assert [line["loc"] for line in bw_log()] == ["agt1001"]
