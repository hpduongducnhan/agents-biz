"""remote_models.fetch (3 dạng provider, phân trang, header key, che key) + studio.provider_models / add_models."""

import uuid

import httpx2
import pytest

from app.agent.config import remote_models
from app.agent.config.remote_models import RemoteError
from tests.agent.helpers import get_root, new_cred
from tests.auth.api import op_path

REAL_CLIENT = httpx2.AsyncClient


class Mock:
    """Thay `httpx2.AsyncClient` trong remote_models bằng MockTransport: ghi request, trả lần lượt các response."""

    def __init__(self, *responses: httpx2.Response | Exception):
        self.responses, self.requests = list(responses), []

    def install(self, monkeypatch):
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            nxt = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

        monkeypatch.setattr(
            remote_models.httpx2, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx2.MockTransport(handler), **kw)
        )
        return self


def js(body, status=200) -> httpx2.Response:
    return httpx2.Response(status, json=body)


async def test_google_pagination_header_auth_and_parse(monkeypatch):
    page1 = {
        "models": [
            {
                "name": "models/gemini-2.5-pro",
                "displayName": "Gemini 2.5 Pro",
                "description": "d",
                "inputTokenLimit": 1048576,
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            },
            {"name": "models/embed-1", "supportedGenerationMethods": ["embedContent"], "inputTokenLimit": 2048},
        ],
        "nextPageToken": "TOK2",
    }
    page2 = {"models": [{"name": "models/gemini-flash", "supportedGenerationMethods": ["generateContent"]}]}
    mock = Mock(js(page1), js(page2)).install(monkeypatch)
    models, ms = await remote_models.fetch("google_genai", "https://g.test/v1beta", "SECRETKEY", {"x-extra": "1"})
    assert ms >= 0 and len(mock.requests) == 2
    first, second = mock.requests
    assert first.headers["x-goog-api-key"] == "SECRETKEY" and first.headers["x-extra"] == "1"
    assert "key=" not in str(first.url) and "key=" not in str(second.url)
    assert first.url.params["pageSize"] == "1000" and "pageToken" not in first.url.params
    assert second.url.params["pageToken"] == "TOK2" and first.url.path == "/v1beta/models"
    assert [m.model_id for m in models] == ["gemini-2.5-pro", "gemini-flash", "embed-1"]  # chat trước, rồi theo tên
    pro = models[0]
    assert (pro.name, pro.description, pro.context_window, pro.chat) == ("Gemini 2.5 Pro", "d", 1048576, True)
    assert models[1].name == "gemini-flash" and models[1].context_window is None
    assert models[2].chat is False


async def test_anthropic_pagination_and_headers(monkeypatch):
    p1 = {"data": [{"id": "claude-a", "display_name": "Claude A", "max_input_tokens": 200000}], "has_more": True}
    p1["last_id"] = "claude-a"
    p2 = {"data": [{"id": "claude-b"}, {"id": "claude-a"}], "has_more": False, "last_id": "claude-b"}
    mock = Mock(js(p1), js(p2)).install(monkeypatch)
    models, _ = await remote_models.fetch("anthropic", "https://a.test/v1", "AK", None)
    first, second = mock.requests
    assert first.headers["x-api-key"] == "AK" and first.headers["anthropic-version"]
    assert "authorization" not in first.headers
    assert first.url.params["limit"] == "1000" and "after_id" not in first.url.params
    assert second.url.params["after_id"] == "claude-a" and len(mock.requests) == 2
    assert [(m.model_id, m.name, m.context_window, m.chat) for m in models] == [
        ("claude-a", "Claude A", 200000, True),
        ("claude-b", "claude-b", None, True),
    ]


@pytest.mark.parametrize("kind", ["openai", "openai_compatible"])
async def test_openai_bearer_pricing_and_chat_flag(monkeypatch, kind):
    body = {
        "data": [
            {"id": "gpt-4o", "context_window": 128000},
            {
                "id": "vendor/large",
                "name": "Large",
                "context_length": 200000,
                "pricing": {
                    "prompt": "0.000002",
                    "completion": "0.000008",
                    "input_cache_read": "0.0000005",
                },
            },
            {"id": "text-embedding-3", "pricing": {"prompt": "-1"}},
            *({"id": i} for i in ("whisper-1", "tts-1", "dall-e-3", "omni-moderation", "x-transcribe", "gpt-image-1")),
            {"id": "gpt-audio"},
            {"id": "rerank-v3"},
            {"id": ""},
            "junk",
        ]
    }
    mock = Mock(js(body)).install(monkeypatch)
    models, _ = await remote_models.fetch(kind, "https://o.test/v1", "SK")
    assert mock.requests[0].headers["authorization"] == "Bearer SK" and not mock.requests[0].url.params
    by = {m.model_id: m for m in models}
    assert by["vendor/large"].input_price_per_1m == 2 and by["vendor/large"].output_price_per_1m == 8
    assert by["vendor/large"].cache_read_price_per_1m == 0.5 and by["vendor/large"].context_window == 200000
    assert by["gpt-4o"].input_price_per_1m is None and by["gpt-4o"].context_window == 128000
    assert by["text-embedding-3"].input_price_per_1m is None  # giá âm → bỏ
    assert {i for i, m in by.items() if m.chat} == {"gpt-4o", "vendor/large"}
    assert [m.model_id for m in models][:2] == ["gpt-4o", "vendor/large"] and "" not in by


async def test_max_pages_and_dedupe(monkeypatch):
    mock = Mock(js({"models": [{"name": "models/a"}], "nextPageToken": "t"})).install(monkeypatch)
    models, _ = await remote_models.fetch("google_genai", "https://g.test", "K")
    assert len(mock.requests) == remote_models.MAX_PAGES and [m.model_id for m in models] == ["a"]


async def test_errors_mask_key(monkeypatch):
    Mock(httpx2.Response(401, text="invalid key SECRETKEY " + "x" * 400)).install(monkeypatch)
    with pytest.raises(RemoteError) as e:
        await remote_models.fetch("openai", "https://o.test", "SECRETKEY")
    assert e.value.status == 401 and "SECRETKEY" not in e.value.detail and "***" in e.value.detail
    assert len(e.value.detail) <= 300
    Mock(httpx2.ConnectError("boom SECRETKEY")).install(monkeypatch)
    with pytest.raises(RemoteError) as e:
        await remote_models.fetch("openai", "https://o.test", "SECRETKEY")
    assert e.value.status == 0 and "SECRETKEY" not in e.value.detail and "ConnectError" in e.value.detail
    Mock(httpx2.Response(200, text="not json")).install(monkeypatch)
    with pytest.raises(RemoteError) as e:
        await remote_models.fetch("openai", "https://o.test", "K")
    assert e.value.status == 0


def test_base_url_default_and_strip():
    assert remote_models.base_url("openai", None) == "https://api.openai.com/v1"
    assert remote_models.base_url("openai_compatible", None) == ""
    assert remote_models.base_url("anthropic", "https://x.test/v1/") == "https://x.test/v1"


# --- ops ---


@pytest.fixture
async def root(api, aenv):
    return api, await get_root(api)


async def provider(api, r, fake_llm, name="fake"):
    return await api.post("studio.save_provider", r, name=name, kind="openai_compatible", base_url=fake_llm.base_url)


async def test_provider_models_lists_and_flags_added(root, fake_llm):
    api, r = root
    p = await provider(api, r, fake_llm)
    cred = await new_cred(api, r, p["id"], "k1")
    await api.post("studio.save_model", r, provider_id=p["id"], model_id="fake-model", name="FM")
    out = await api.get("studio.provider_models", r, provider_id=p["id"])
    assert out["credential_id"] == cred["id"] and out["latency_ms"] >= 0
    by = {m["model_id"]: m for m in out["models"]}
    assert set(by) == {"fake-model", "fake-embed", "fake/large"}
    assert by["fake-model"]["added"] is True and by["fake/large"]["added"] is False
    assert by["fake-embed"]["chat"] is False and by["fake/large"]["chat"] is True
    assert float(by["fake/large"]["input_price_per_1m"]) == 2 and float(by["fake/large"]["output_price_per_1m"]) == 8
    assert by["fake/large"]["context_window"] == 128000
    assert by["fake-model"]["input_price_per_1m"] is None
    assert [m["model_id"] for m in out["models"]][-1] == "fake-embed"
    # model của provider khác không tính là đã thêm
    p2 = await provider(api, r, fake_llm, "other")
    await new_cred(api, r, p2["id"], "k2")
    other = await api.get("studio.provider_models", r, provider_id=p2["id"])
    assert not any(m["added"] for m in other["models"])


async def test_credential_auto_pick_bound_then_unbound(root, fake_llm):
    api, r = root
    p = await provider(api, r, fake_llm)
    q = {"provider_id": p["id"]}
    assert await api.err("GET", "studio.provider_models", r, params=q) == (409, 6010)
    unbound = await new_cred(api, r, None, "free")
    other_p = await provider(api, r, fake_llm, "other")
    await new_cred(api, r, other_p["id"], "theirs")  # key gắn provider khác: không được chọn
    assert (await api.get("studio.provider_models", r, **q))["credential_id"] == unbound["id"]
    bound = await new_cred(api, r, p["id"], "mine")
    assert (await api.get("studio.provider_models", r, **q))["credential_id"] == bound["id"]
    await api.post("credentials.update", r, credential_id=bound["id"], status="disabled")
    assert (await api.get("studio.provider_models", r, **q))["credential_id"] == unbound["id"]
    await api.post("credentials.update", r, credential_id=unbound["id"], status="disabled")
    assert await api.err("GET", "studio.provider_models", r, params=q) == (409, 6010)
    # chọn key cụ thể thì dùng đúng key đó dù đã tắt
    out = await api.get("studio.provider_models", r, provider_id=p["id"], credential_id=bound["id"])
    assert out["credential_id"] == bound["id"]


async def test_oldest_bound_key_wins(root, fake_llm):
    api, r = root
    p = await provider(api, r, fake_llm)
    first = await new_cred(api, r, p["id"], "a1")
    await new_cred(api, r, p["id"], "a2")
    assert (await api.get("studio.provider_models", r, provider_id=p["id"]))["credential_id"] == first["id"]


async def test_provider_models_remote_error_6011(root, fake_llm):
    api, r = root
    p = await provider(api, r, fake_llm)
    bad = await new_cred(api, r, p["id"], "bad", "bad-key")
    resp = await api.call(
        "GET", op_path("studio.provider_models"), r, params={"provider_id": p["id"], "credential_id": bad["id"]}
    )
    assert resp.status_code == 502
    body = resp.json()
    assert body["code"] == 6011 and body["data"]["status"] == 401
    assert "Incorrect API key" in body["data"]["detail"] and "bad-key" not in body["data"]["detail"]
    dead = await api.post(
        "studio.save_provider", r, name="dead", kind="openai_compatible", base_url="http://127.0.0.1:1/v1"
    )
    resp = await api.call(
        "GET", op_path("studio.provider_models"), r, params={"provider_id": dead["id"], "credential_id": bad["id"]}
    )
    assert resp.status_code == 502 and resp.json()["data"]["status"] == 0 and resp.json()["data"]["detail"]


async def test_provider_models_not_found_and_superadmin_only(root, fake_llm):
    api, r = root
    ghost = {"provider_id": str(uuid.uuid4())}
    assert await api.err("GET", "studio.provider_models", r, params=ghost) == (404, 1001)
    p = await provider(api, r, fake_llm)
    admin = await api.as_user("adm@x.io", roles=("admin",))
    assert await api.err("GET", "studio.provider_models", admin, params={"provider_id": p["id"]}) == (403, 1005)
    body = {"provider_id": p["id"], "models": [{"model_id": "m", "name": "M"}]}
    assert await api.err("POST", "studio.add_models", admin, json=body) == (403, 1005)


async def test_add_models_skip_dup_and_prices(root, fake_llm):
    api, r = root
    p = await provider(api, r, fake_llm)
    await api.post("studio.save_model", r, provider_id=p["id"], model_id="have", name="Have")
    models = [
        {"model_id": "have", "name": "Have 2"},
        {"model_id": "new", "name": "New", "context_window": 4096, "input_price_per_1m": "2", "output_price_per_1m": 8},
        {"model_id": "new", "name": "New dup"},
        {"model_id": "plain", "name": "Plain"},
    ]
    out = await api.post("studio.add_models", r, provider_id=p["id"], models=models)
    assert out == {"added": 2, "skipped": 2}
    listed = await api.get("studio.list_models", r, provider_id=p["id"])
    by = {m["model_id"]: m for m in listed}
    assert set(by) == {"have", "new", "plain"} and by["have"]["name"] == "Have"
    assert by["new"]["name"] == "New" and by["new"]["context_window"] == 4096
    assert float(by["new"]["input_price_per_1m"]) == 2 and float(by["new"]["output_price_per_1m"]) == 8
    assert float(by["plain"]["input_price_per_1m"]) == 0
    again = await api.post("studio.add_models", r, provider_id=p["id"], models=models)
    assert again == {"added": 0, "skipped": 4}


async def test_add_models_validation(root, fake_llm):
    api, r = root
    p = await provider(api, r, fake_llm)
    many = [{"model_id": f"m{i}", "name": f"M{i}"} for i in range(101)]
    assert (await api.err("POST", "studio.add_models", r, json={"provider_id": p["id"], "models": many}))[1] == 1002
    assert (await api.err("POST", "studio.add_models", r, json={"provider_id": p["id"], "models": []}))[1] == 1002
    ok = await api.post("studio.add_models", r, provider_id=p["id"], models=many[:100])
    assert ok == {"added": 100, "skipped": 0}
    body = {"provider_id": str(uuid.uuid4()), "models": [{"model_id": "m", "name": "M"}]}
    assert await api.err("POST", "studio.add_models", r, json=body) == (404, 1001)


async def test_test_provider_uses_remote_fetch(root, fake_llm):
    api, r = root
    p = await provider(api, r, fake_llm)
    good = await new_cred(api, r, p["id"], "good")
    out = await api.post("studio.test_provider", r, provider_id=p["id"], credential_id=good["id"])
    assert out["ok"] is True and set(out["models"]) == {"fake-model", "fake-embed", "fake/large"}
    bad = await new_cred(api, r, p["id"], "bad", "bad-key")
    out = await api.post("studio.test_provider", r, provider_id=p["id"], credential_id=bad["id"])
    assert out["ok"] is False and out["error"].startswith("HTTP 401: ") and "bad-key" not in out["error"]


def test_int_ignores_garbage():
    assert remote_models._int("abc") is None and remote_models._int(0) is None and remote_models._int("42") == 42
