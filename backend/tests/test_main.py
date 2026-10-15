"""App `api`: middleware log HTTP gắn ngoài cùng — mọi response có cid, mỗi request một dòng log."""

import logging

import pytest

from app import main, observability
from app.core.httpx_log import uninstall_httpx_logging
from app.core.messaging.hub import has_hub
from app.core.settings import Settings
from app.main import create_app
from app.observability.sinks import get_sinks
from tests.conftest import asgi_client


async def test_api_logs_each_request_once_with_cid(bw_log):
    app = create_app(Settings(_env_file=None), connect=False)
    async with asgi_client(app) as c:
        r = await c.get("/bizwithagents/api/khong-co", headers={"X-Correlation-ID": "cid-main-1"})
    assert r.status_code == 404 and r.headers["x-correlation-id"] == "cid-main-1"
    lines = [line for line in bw_log() if line["loc"] == "http0001"]
    assert len(lines) == 1 and lines[0]["http"]["status"] == 404 and lines[0]["level"] == "WARNING"


async def test_inbound_log_can_be_turned_off_but_cid_stays(bw_log):
    app = create_app(Settings(_env_file=None, LOG_HTTP_IN=False), connect=False)
    async with asgi_client(app) as c:
        r = await c.get("/bizwithagents/api/khong-co", headers={"X-Correlation-ID": "cid-main-2"})
    assert r.headers["x-correlation-id"] == "cid-main-2"
    assert not [line for line in bw_log() if line["loc"] == "http0001"]


def test_bad_rules_file_stops_the_app(tmp_path):
    bad = tmp_path / "rules.yaml"
    bad.write_text("khac: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="http_log"):
        create_app(Settings(_env_file=None, LOG_HTTP_RULES_FILE=str(bad)), connect=False)


async def test_api_lifespan_installs_outbound_patch(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "install_httpx_logging", lambda rules, keys, *, log: calls.append(log) or [])
    app = main.create_app(Settings(_env_file=None, LOG_HTTP_OUT=False), connect=False)
    async with app.router.lifespan_context(app):
        pass
    assert calls == [False]  # LOG_HTTP_OUT=false chỉ tắt dòng log — bản vá vẫn cài cho http_capture
    logging.getLogger().handlers.clear()


@pytest.mark.integration
async def test_api_lifespan_boots_with_mongo_disabled(test_settings, bw_log, monkeypatch):
    monkeypatch.setitem(observability._state, "warned", False)
    s = test_settings.model_copy(update={"MONGO_ENABLED": False, "MONGO_RW_URL": ""})
    app = create_app(s)
    try:
        async with app.router.lifespan_context(app):
            assert has_hub() and get_sinks().enabled is False
            async with asgi_client(app) as c:
                r = await c.get("/bizwithagents/api/health/ready")
            assert r.status_code == 200 and r.json()["data"]["mongo"] == "disabled"
        assert not has_hub()
        assert any(line["loc"] == "obs0001" for line in bw_log())
    finally:
        logging.getLogger().handlers.clear()
        uninstall_httpx_logging()
