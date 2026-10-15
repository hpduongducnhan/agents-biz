"""R7: `frontend/src/lib/api/openapi.json` là hợp đồng duy nhất backend ↔ frontend — sinh ổn định, chỉ chứa app thật,
bản commit phải khớp app hiện tại."""

import json

from typer.testing import CliRunner

from app.cli import cli
from app.core.settings import Settings
from app.main import OPENAPI_FILE, render_openapi

runner = CliRunner()


def test_render_is_stable_sorted_and_app_only():
    first = render_openapi(Settings(_env_file=None))
    assert first == render_openapi(Settings(_env_file=None)) and first.endswith("\n")
    doc = json.loads(first)
    assert list(doc) == sorted(doc) and doc["info"]["title"] == "BizWithAgents"
    assert "/bizwithagents/api/health/live" in doc["paths"]
    assert not [p for p in doc["paths"] if p.startswith("/bizwithagents/api/fx/")]  # miền giả của test không lọt (Q5)


def test_committed_openapi_is_current():
    assert OPENAPI_FILE.is_file(), "chưa có openapi.json — chạy `make openapi` rồi commit"
    expected = render_openapi(Settings(_env_file=None))
    assert OPENAPI_FILE.read_text(encoding="utf-8") == expected, "openapi.json cũ — chạy `make openapi` rồi commit"


def test_cli_writes_then_checks(tmp_path):
    out = tmp_path / "api" / "openapi.json"
    assert runner.invoke(cli, ["dump-openapi", "--out", str(out)]).exit_code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["info"]["title"] == "BizWithAgents"
    assert runner.invoke(cli, ["dump-openapi", "--out", str(out), "--check"]).exit_code == 0
    out.write_text("{}\n", encoding="utf-8")
    assert runner.invoke(cli, ["dump-openapi", "--out", str(out), "--check"]).exit_code == 1
