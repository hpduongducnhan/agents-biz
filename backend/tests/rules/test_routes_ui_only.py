"""Mọi route của app `api` sinh từ @operation, hoặc viết tay có `ui_only(reason)`; hàm public trong
`app/<miền>/ops.py` phải là @operation hoặc ui_only."""

import importlib
import importlib.util
import inspect

from app.core.settings import Settings
from app.domains import DOMAINS, load_domains
from app.main import create_app
from tests.conftest import api_routes


def _unmarked(app) -> list[str]:
    out = []
    for r in api_routes(app):
        if not (hasattr(r.endpoint, "__bw_operation__") or hasattr(r.endpoint, "__bw_ui_only__")):
            out.append(f"{','.join(sorted(r.methods))} {r.path}")
    return sorted(out)


def test_every_route_is_operation_or_ui_only():
    assert _unmarked(create_app(Settings(_env_file=None), connect=False)) == []


def test_checker_catches_handwritten_route():
    app = create_app(Settings(_env_file=None), connect=False)

    @app.get("/bizwithagents/api/viet-tay")
    async def handwritten():
        return {}

    assert _unmarked(app) == ["GET /bizwithagents/api/viet-tay"]


def test_public_functions_in_ops_modules_are_operations():
    load_domains()
    missing = []
    for domain in DOMAINS:
        name = f"app.{domain}.ops"
        if importlib.util.find_spec(name) is None:
            continue
        module = importlib.import_module(name)
        for fname, func in inspect.getmembers(module, inspect.iscoroutinefunction):
            if func.__module__ != name or fname.startswith("_"):
                continue
            if not (hasattr(func, "__bw_operation__") or hasattr(func, "__bw_ui_only__")):
                missing.append(f"{name}.{fname}")
    assert missing == [], "hàm public thiếu @operation / ui_only:\n  " + "\n  ".join(missing)
