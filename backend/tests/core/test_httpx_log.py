import httpx
import httpx2
import pytest

from app.core.cid import set_cid
from app.core.http_rules import HttpLogRule, HttpLogRules
from app.core.httpx_log import install_httpx_logging, uninstall_httpx_logging
from app.core.redact import build_keys

KEYS = build_keys(())


@pytest.fixture(autouse=True)
def _restore():
    yield
    uninstall_httpx_logging()


def partner_rules(**flags) -> HttpLogRules:
    return HttpLogRules(inbound=[], outbound=[HttpLogRule(match="https://api.partner.test/**", **flags)])


def out_lines(bw_log, loc="hout0001"):
    return [line for line in bw_log() if line["loc"] == loc]


@pytest.mark.parametrize("lib", [httpx2, httpx])
async def test_logs_metadata_and_redacts_query(lib, bw_log):
    assert set(install_httpx_logging(HttpLogRules.empty(), KEYS)) == {"httpx2", "httpx"}
    transport = lib.MockTransport(lambda req: lib.Response(201, json={"ok": True}))
    async with lib.AsyncClient(transport=transport) as c:
        await c.get("https://x.test/a?api_key=zzz&q=1")
    h = out_lines(bw_log)[-1]["http"]
    assert h["status"] == 201 and h["lib"] == lib.__name__ and h["dir"] == "out"
    assert "zzz" not in h["url"] and "q=1" in h["url"]
    assert "resp_body" not in h


async def test_rule_captures_bodies_propagates_cid_and_redacts(bw_log):
    seen = {}

    def handler(req):
        seen["cid"] = req.headers.get("x-correlation-id")
        return httpx2.Response(200, json={"token": "t0p", "v": 1}, headers={"set-cookie": "s=1"})

    install_httpx_logging(partner_rules(req_body=True, resp_body=True, resp_headers=True, propagate_cid=True), KEYS)
    set_cid("cid-9")
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as c:
        await c.post("https://api.partner.test/v1/login", json={"user": "a", "password": "hunter2"})
    assert seen["cid"] == "cid-9"
    h = out_lines(bw_log)[-1]["http"]
    assert "hunter2" not in h["req_body"]
    assert "t0p" not in h["resp_body"] and '"v": 1' in h["resp_body"]
    assert h["resp_headers"]["set-cookie"] == "[REDACTED]"


async def test_no_cid_header_without_rule():
    seen = {}

    def handler(req):
        seen["cid"] = req.headers.get("x-correlation-id")
        return httpx2.Response(200)

    install_httpx_logging(HttpLogRules.empty(), KEYS)
    set_cid("cid-10")
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as c:
        await c.get("https://other.test/")
    assert seen["cid"] is None


async def test_stream_response_body_not_consumed(bw_log):
    install_httpx_logging(partner_rules(resp_body=True), KEYS)
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, content=b"chunk-data"))
    async with httpx2.AsyncClient(transport=transport) as c:
        async with c.stream("GET", "https://api.partner.test/s") as r:
            data = await r.aread()
    assert data == b"chunk-data"
    h = out_lines(bw_log)[-1]["http"]
    assert "resp_body" not in h and "resp_bytes" not in h


async def test_network_error_logged_and_reraised(bw_log):
    def handler(req):
        raise httpx2.ConnectError("down", request=req)

    install_httpx_logging(HttpLogRules.empty(), KEYS)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as c:
        with pytest.raises(httpx2.ConnectError):
            await c.get("https://down.test/")
    line = out_lines(bw_log, "hout0500")[-1]
    assert line["level"] == "WARNING" and line["http"]["error"] == "ConnectError"


def test_sync_client_patched(bw_log):
    install_httpx_logging(HttpLogRules.empty(), KEYS)
    with httpx2.Client(transport=httpx2.MockTransport(lambda req: httpx2.Response(503))) as c:
        c.get("https://x.test/")
    line = out_lines(bw_log)[-1]
    assert line["level"] == "ERROR" and line["http"]["status"] == 503


def test_install_is_idempotent_and_uninstall_restores():
    original = httpx2.AsyncClient.send
    install_httpx_logging(HttpLogRules.empty(), KEYS)
    patched = httpx2.AsyncClient.send
    install_httpx_logging(HttpLogRules.empty(), KEYS)
    assert httpx2.AsyncClient.send is patched
    assert patched.__wrapped__ is original
    uninstall_httpx_logging()
    assert httpx2.AsyncClient.send is original


async def test_logging_failure_never_breaks_the_call(monkeypatch, bw_log):
    import app.core.httpx_log as hx

    def boom(*args, **kwargs):
        raise RuntimeError("render hỏng")

    monkeypatch.setattr(hx, "render_body", boom)
    install_httpx_logging(partner_rules(resp_body=True), KEYS)
    transport = httpx2.MockTransport(lambda req: httpx2.Response(200, json={"ok": True}))
    async with httpx2.AsyncClient(transport=transport) as c:
        r = await c.get("https://api.partner.test/x")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert any(line["loc"] == "hout0501" for line in bw_log())
