"""Webhook của hook: POST JSON ký HMAC-SHA256 bằng secret credential, timeout 10 s, event log, `studio.test_hook`."""

import hashlib
import hmac
import json
import uuid

import httpx2
import pytest

from app.agent.hooks import webhook
from app.agent.testing import fake_llm as fl
from tests.agent.helpers import get_root, new_cred

PAYLOAD = {"hook_id": "h", "point": "after_run", "agent": "assistant", "data": {"run": {"status": "done"}, "tên": "An"}}


class Capture:
    """Thay `httpx2.AsyncClient` trong module webhook bằng client MockTransport — ghi request, trả status chọn trước."""

    def __init__(self, status: int = 200, exc: Exception | None = None):
        self.status, self.exc, self.requests = status, exc, []

    def factory(self, real):
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            if self.exc:
                raise self.exc
            return httpx2.Response(self.status, json={"ok": True})

        def make(**kw):
            return real(transport=httpx2.MockTransport(handler), **kw)

        return make


@pytest.fixture
def capture(monkeypatch):
    cap = Capture()
    monkeypatch.setattr(webhook.httpx2, "AsyncClient", cap.factory(httpx2.AsyncClient))
    return cap


def test_sign_and_body_are_stable():
    body = webhook.body_of(PAYLOAD)
    assert body == json.dumps(PAYLOAD, ensure_ascii=False, separators=(",", ":")).encode() and "tên".encode() in body
    expect = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert webhook.sign("s3cret", body) == expect
    assert webhook.sign("khác", body) != expect


async def test_notify_and_webhook_hmac(api, aenv, memory_sinks, capture):
    root = await get_root(api)
    cred = await new_cred(api, root, None, "hook-secret", "whsec_abcdef123456")
    out = await webhook.send_webhook("h1", "https://hook.test/in?token=zzz", PAYLOAD, cred["id"], str(uuid.uuid4()))
    assert out == {"ok": True, "status": 200}
    (req,) = capture.requests
    body = req.content
    assert req.method == "POST" and req.headers["content-type"] == "application/json" and json.loads(body) == PAYLOAD
    assert req.headers[webhook.SIGNATURE] == webhook.sign("whsec_abcdef123456", body)
    (entry,) = [e for e in memory_sinks.events.entries if e.operation == "agent.hook_webhook"]
    assert entry.operation == "agent.hook_webhook" and entry.ok and entry.source == "system"
    assert entry.input == {"hook_id": "h1", "url": "https://hook.test/in", "status": 200}  # query bị bỏ khỏi log
    assert entry.agent_run_id is not None and entry.error_code is None and entry.duration_ms >= 0


async def test_webhook_without_credential_is_unsigned(aenv, memory_sinks, capture):
    await webhook.send_webhook("h", "https://hook.test/x", PAYLOAD)
    assert webhook.SIGNATURE not in capture.requests[0].headers
    assert memory_sinks.events.entries[0].agent_run_id is None


@pytest.mark.parametrize("status", [400, 500])
async def test_webhook_http_error_logs_ok_false(aenv, memory_sinks, capture, status, bw_log):
    capture.status = status
    out = await webhook.send_webhook("h", "https://hook.test/x", PAYLOAD)
    assert out == {"ok": False, "status": status}
    entry = memory_sinks.events.entries[0]
    assert entry.ok is False and entry.error_code == 6018 and entry.input["status"] == status
    assert any(r.get("loc") == "agt0701" for r in bw_log())


async def test_webhook_network_error_or_timeout_never_raises(aenv, memory_sinks, capture, bw_log):
    capture.exc = httpx2.ReadTimeout("quá 10 s")
    out = await webhook.send_webhook("h", "https://hook.test/x", PAYLOAD)
    assert out == {"ok": False, "status": None}
    assert memory_sinks.events.entries[0].ok is False and webhook.TIMEOUT_SEC == 10.0
    assert any(r.get("loc") == "agt0702" for r in bw_log())


async def test_webhook_missing_credential_is_reported_as_failure(aenv, memory_sinks, capture):
    out = await webhook.send_webhook("h", "https://hook.test/x", PAYLOAD, str(uuid.uuid4()))
    assert out["ok"] is False and capture.requests == []
    assert memory_sinks.events.entries[0].error_code == 6018


async def test_event_log_write_failure_is_only_logged(aenv, memory_sinks, capture, monkeypatch, bw_log):
    async def boom(entry):
        raise ConnectionError("mongo down")

    monkeypatch.setattr(memory_sinks.events, "write", boom)
    assert (await webhook.send_webhook("h", "https://hook.test/x", PAYLOAD))["ok"] is True
    assert any(r.get("loc") == "agt0703" for r in bw_log())


async def test_webhook_roundtrip_to_fake_llm_hooks_endpoint(aenv, memory_sinks, fake_llm):
    url = fake_llm.base_url.removesuffix("/v1") + "/hooks/run-done"
    out = await webhook.send_webhook("h", url, PAYLOAD)
    assert out == {"ok": True, "status": 200}
    assert fl.HOOK_CALLS == [{"path": "/hooks/run-done", "body": PAYLOAD}]


async def test_test_hook_dry_run(api, aenv, fake_llm):
    root = await get_root(api)
    cred = await new_cred(api, root, None, "dry-secret", "whsec_dry_1234567")
    base = {
        "point": "before_tool",
        "sample": {"args": {"amount": 5_000_000}, "user": {"name": "An"}, "agent": {"slug": "assistant"}},
    }
    cond = [{"path": "args.amount", "op": "gt", "value": 1_000_000}]
    blocked = await api.post(
        "studio.test_hook", root, **base, conditions=cond, action={"action": "block", "message": "Cấm {{user.name}}"}
    )
    assert blocked["matched"] and blocked["blocked"] and blocked["message"] == "Cấm An" and blocked["approval"] is False
    approval = await api.post("studio.test_hook", root, **base, conditions=cond, action={"action": "require_approval"})
    assert approval["approval"] and not approval["blocked"]
    miss = await api.post(
        "studio.test_hook",
        root,
        **base,
        conditions=[{"path": "args.amount", "op": "lt", "value": 1}],
        action={"action": "block", "message": "x"},
    )
    assert miss["matched"] is False and miss["results"] == []
    hook_url = fake_llm.base_url.removesuffix("/v1") + "/hooks/x"
    dry = await api.post(
        "studio.test_hook", root, **base, action={"action": "webhook", "url": hook_url, "credential_id": cred["id"]}
    )
    (res,) = dry["results"]
    assert (
        res["sent"] is False
        and res["request"]["url"] == hook_url
        and res["request"]["headers"][webhook.SIGNATURE].startswith("sha256=")
    )
    assert json.loads(res["request"]["body"])["data"] == base["sample"] and fl.HOOK_CALLS == []  # không gửi thật
    ctx = await api.post(
        "studio.test_hook",
        root,
        point="before_run",
        action={"action": "add_context", "text": "Chào {{user.name}}"},
        sample=base["sample"],
    )
    assert ctx["context"] == ["Chào An"]
    bad = {"point": "after_run", "action": {"action": "block", "message": "x"}}
    assert await api.err("POST", "studio.test_hook", root, json=bad) == (422, 6017)
