"""Route mà smoke đầu-cuối (realtime/scripts/smoke_e2e.ts) gọi — quy ước REST suy từ tên
operation. Đổi tên / method một operation dưới đây → sửa cùng lúc smoke + helper E2E (R7)."""

import json
import os
import subprocess
import sys
from pathlib import Path

from app.core.settings import Settings
from app.main import create_app
from tests.conftest import api_routes

PREFIX = "/bizwithagents/api"
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SMOKE_ROUTES = {
    ("get", "/health/live"),
    ("get", "/health/ready"),
    ("get", "/health/pipeline"),
    ("post", "/auth/register"),
    ("post", "/auth/login"),
    ("post", "/auth/refresh"),
    ("post", "/auth/logout"),
    ("get", "/auth/me"),
    ("post", "/admin/update_user"),
    ("post", "/rbac/create_role"),
    ("post", "/notifications/send_test"),
    ("get", "/observability/list_events"),
    ("get", "/observability/list_issues"),
    ("get", "/system/public_info"),
    ("get", "/system/status"),
    ("post", "/tenants/create"),
    ("get", "/invites/preview"),
    ("get", "/mail/outbox"),
    ("get", "/admin/list_users"),
    ("post", "/tenant/update"),
    ("post", "/auth/forgot_password"),
    ("post", "/auth/reset_password"),
    ("post", "/tenants/update"),
    ("post", "/agent/send"),
    ("get", "/agent/get_session"),
    ("get", "/agent/list_agents"),
    ("post", "/tasks/create"),
    ("get", "/tasks/get"),
    ("get", "/tasks/list"),
}
DEV_ROUTES = {("post", "/devtools/raise_error")}


def _routes(env: str) -> set[tuple[str, str]]:
    app = create_app(Settings(_env_file=None, ENV=env, SUPERADMIN_EMAILS="root@test.local"), connect=False)
    return {(m.lower(), r.path) for r in api_routes(app) for m in r.methods}


def test_routes_used_by_smoke_and_e2e_exist_in_dev_app():
    routes = _routes("dev")
    want = SMOKE_ROUTES | DEV_ROUTES
    missing = sorted(f"{m.upper()} {PREFIX}{p}" for m, p in want if (m, PREFIX + p) not in routes)
    assert not missing, "route smoke / E2E cần mà app không có:\n  " + "\n  ".join(missing)


def test_contract_file_has_smoke_routes_but_never_devtools():
    """R7: openapi.json đã commit có mọi route smoke gọi; /devtools/* không bao giờ vào hợp đồng."""
    paths = json.loads((ROOT / "frontend/src/lib/api/openapi.json").read_text())["paths"]

    def ops(p: str) -> dict:
        return paths.get(PREFIX + p) or paths.get(p) or {}

    missing = sorted(f"{m.upper()} {p}" for m, p in SMOKE_ROUTES if m not in ops(p))
    assert not missing, "openapi.json thiếu (chạy make openapi?):\n  " + "\n  ".join(missing)
    assert not [p for p in paths if "/devtools/" in p]


def test_prod_app_has_no_devtools_routes():
    assert not [p for _, p in _routes("prod") if "/devtools/" in p]


def test_prod_process_never_imports_devtools():
    """Process ENV=prod (như Coolify) không import app.devtools.ops."""
    code = (
        "import sys\n"
        "from app.core.settings import Settings\n"
        "from app.main import create_app\n"
        "create_app(Settings(_env_file=None, ENV='prod', SUPERADMIN_EMAILS='root@test.local'), connect=False)\n"
        "sys.exit(1 if 'app.devtools.ops' in sys.modules else 0)\n"
    )
    env = os.environ | {"ENV": "prod"}
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
