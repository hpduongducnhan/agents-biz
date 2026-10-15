"""Điểm bắt lỗi → issue: HTTP 5xx chưa xử lý, task hết lượt / consumer / socket — luật AST giữ cả 4."""

import ast
from pathlib import Path

import pytest

from app.main import create_app
from tests.conftest import asgi_client
from tests.platform_env import eventually

APP = Path(__file__).resolve().parents[2] / "app"
POINTS = {
    "core/exception_handlers.py": {"exc0500"},
    "core/messaging/tasks.py": {"tq0500"},
    "core/messaging/consumer.py": {"bus0500", "ws0500"},
}
SECRET = "abcdefghijklmnopqrstu"


def _log_locs(fn: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "loc" and isinstance(value, ast.Constant):
                    out.add(value.value)
    return out


def _capture_locs(fn: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "capture_issue":
            out |= {kw.value.value for kw in node.keywords if kw.arg == "loc" and isinstance(kw.value, ast.Constant)}
    return out


@pytest.mark.parametrize("rel", sorted(POINTS))
def test_every_unexpected_error_branch_captures_an_issue(rel):
    tree = ast.parse((APP / rel).read_text(encoding="utf-8"))
    seen: set[str] = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            need = _log_locs(fn) & POINTS[rel]
            assert need <= _capture_locs(fn), f"{rel}:{fn.name} log {need} mà không capture_issue"
            seen |= need
    assert seen == POINTS[rel], f"{rel}: thiếu điểm bắt {POINTS[rel] - seen}"


def _boom_app(settings):
    app = create_app(
        settings.model_copy(update={"DEBUG": False}), connect=False
    )  # debug=True → Starlette trả trang traceback thay envelope

    async def boom():
        raise RuntimeError(f"hỏng với Bearer {SECRET}")

    app.add_api_route("/bizwithagents/api/__boom", boom)
    return app


async def test_unhandled_http_error_is_captured_with_request_context(test_settings, memory_sinks):
    async with asgi_client(_boom_app(test_settings)) as client:
        r = await client.get("/bizwithagents/api/__boom")
    assert r.status_code == 500 and r.json()["code"] == 1000
    [item] = memory_sinks.issues.items
    assert (item["source"], item["loc"]) == ("http", "exc0500")
    assert item["context"]["method"] == "GET" and item["context"]["path"] == "/bizwithagents/api/__boom"


@pytest.mark.integration
async def test_unhandled_http_error_lands_in_issues(stack):
    async with asgi_client(_boom_app(stack.settings)) as client:
        r = await client.get("/bizwithagents/api/__boom")
    assert r.status_code == 500 and r.json()["code"] == 1000  # cả hai chế độ: envelope đúng, không lỗi thêm
    if stack.settings.MONGO_ENABLED:
        issues = stack.conns.mongo.rw["issues"]
        doc = await eventually(lambda: issues.find_one({"source": "http"}))
        assert doc["loc"] == "exc0500" and doc["count"] == 1 and doc["sample"]["path"] == "/bizwithagents/api/__boom"
        assert SECRET not in doc["sample"]["traceback"] and SECRET not in doc["title"]
