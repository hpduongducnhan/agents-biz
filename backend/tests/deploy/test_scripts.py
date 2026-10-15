"""scripts/smoke_prod.sh + scripts/deploy.sh chạy với server HTTP giả (Coolify + domain) — chứng minh bản mới đã lên."""

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"


def _json(value) -> str:
    """JSON gọn như FastAPI trả thật (`"success":true`) — smoke so chuỗi theo dạng này."""
    return json.dumps(value, separators=(",", ":"))


FAST = {"SMOKE_TRIES": "1", "SMOKE_SLEEP": "0", "DEPLOY_POLLS": "2", "DEPLOY_POLL_SEC": "0"}


def _live(version: str) -> dict:
    return {"success": True, "data": {"status": "ok", "service": "bizwithagents-backend", "version": version}}


ASSET = "/assets/index-abc.js"
HTML = f'<div id="root"></div><script type="module" src="{ASSET}"></script>'
# web giả đúng như nginx của prod: index no-cache, asset immutable, SPA fallback — để smoke đi qua bước "web"
WEB_HEADERS = {"Cache-Control": "no-cache"}
ASSET_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _routes(version: str, deploy_status: str) -> dict[str, tuple[int, str]]:
    ok = _json({"success": True, "data": {}})
    return {
        "GET /": (200, HTML),
        "GET /admin/users": (200, HTML),
        f"GET {ASSET}": (200, "console.log(1)"),
        "GET /bizwithagents/api/health/live": (200, _json(_live(version))),
        "GET /bizwithagents/api/health/ready": (200, _json({"success": True, "data": {"mongo.rw": "ok"}})),
        "GET /bizwithagents/api/health/pipeline": (200, ok),
        "GET /bizwithagents/ws/health": (200, _json({"status": "ok"})),
        "POST /api/v1/deploy": (200, _json({"deployments": [{"deployment_uuid": "dep1"}]})),
        "GET /api/v1/deployments/dep1": (200, _json({"status": deploy_status})),
    }


@pytest.fixture
def stub():
    """Server giả: `stub(version, deploy_status)` → base URL; mọi đường dẫn khác trả 404."""
    servers = []

    def start(version: str = "abc", deploy_status: str = "finished") -> str:
        routes = _routes(version, deploy_status)

        class Handler(BaseHTTPRequestHandler):
            def _reply(self):
                code, body = routes.get(f"{self.command} {self.path}", (404, "not found"))
                data = body.encode()
                self.send_response(code)
                headers = ASSET_HEADERS if self.path == ASSET else {}
                headers = WEB_HEADERS if self.path in ("/", "/admin/users") else headers
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = _reply

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self._reply()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server in servers:
        server.shutdown()


def _run(cmd: list[str], env: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env={**os.environ, **FAST, **env}, cwd=cwd, capture_output=True, text=True, timeout=30)


def _smoke(base: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return _run(["bash", str(SCRIPTS / "smoke_prod.sh"), base], {"SMOKE_EXPECT_VERSION": "", **(env or {})})


@pytest.mark.skipif(shutil.which("node") is None, reason="smoke_prod.sh chạy smoke_e2e.ts bằng Node")
def test_smoke_fails_when_live_version_differs(stub):
    """4 kiểm curl qua, rồi smoke_e2e.ts (Node) bắt version lệch — bước web / version chạy thật với server giả.
    Server giả không có websocket nên bước sau version không được chạy tới (script dừng ở bước đỏ đầu tiên)."""
    res = _smoke(stub(version="old111"), {"SMOKE_EXPECT_VERSION": "new222"})
    assert res.returncode == 1, res.stdout + res.stderr
    assert "✓ web" in res.stdout and "✓ web: bundle + SPA fallback + cache" in res.stdout
    assert "✗ phiên bản api" in res.stdout and "old111" in res.stdout and "new222" in res.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="smoke_prod.sh chạy smoke_e2e.ts bằng Node")
def test_smoke_version_step_passes_when_version_matches(stub):
    res = _smoke(stub(version="new222"), {"SMOKE_EXPECT_VERSION": "new222"})
    assert "✓ phiên bản api = commit vừa deploy" in res.stdout, res.stdout + res.stderr
    assert "✗ phiên bản" not in res.stdout
    assert "chế độ Mongo" not in res.stdout and "✓ api ready + Mongo on" in res.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="smoke_prod.sh chạy smoke_e2e.ts bằng Node")
def test_smoke_skips_version_check_when_not_expected(stub):
    res = _smoke(stub(version="dev"))
    assert "– phiên bản api = commit vừa deploy (bỏ qua" in res.stdout, res.stdout + res.stderr


def test_smoke_without_url_or_public_url_fails_fast(tmp_path):
    env = {"PUBLIC_URL": "", "COOLIFY_ENV_FILE": str(tmp_path / "none.env")}
    res = _run(["bash", str(SCRIPTS / "smoke_prod.sh")], env)
    assert res.returncode != 0 and "URL công khai" in res.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="smoke_prod.sh chạy smoke_e2e.ts bằng Node")
def test_smoke_defaults_to_public_url_from_coolify_env(stub, tmp_path):
    env_file = tmp_path / "coolify.env"
    env_file.write_text(f'COOLIFY_TOKEN=x\nPUBLIC_URL="{stub(version="dev")}/"\n')
    res = _run(["bash", str(SCRIPTS / "smoke_prod.sh")], {"PUBLIC_URL": "", "COOLIFY_ENV_FILE": str(env_file)})
    assert "✓ web" in res.stdout, res.stdout + res.stderr


@pytest.fixture
def repo(tmp_path):
    """Repo git tạm có origin (bare) cùng commit — đủ điều kiện `deploy.sh` (sạch, HEAD = origin/main)."""
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run([*git, "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run([*git, "init", "-q", str(work)], check=True)
    shutil.copytree(SCRIPTS, work / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (work / ".gitignore").write_text(".secrets/\n")
    steps = (
        ["add", "."],
        ["commit", "-qm", "init"],
        ["remote", "add", "origin", str(origin)],
        ["push", "-q", "origin", "main"],
    )
    for args in steps:
        subprocess.run([*git, *args], cwd=work, check=True)
    return work


def _env_file(work: Path, base: str) -> Path:
    path = work / ".secrets" / "coolify.env"
    path.parent.mkdir()
    path.write_text(f"COOLIFY_URL={base}\nCOOLIFY_TOKEN=t\nCOOLIFY_APP_UUID=u\nPUBLIC_URL={base}\n")
    return path


def test_deploy_fails_when_deployment_never_finishes(stub, repo):
    base = stub(deploy_status="in_progress")
    res = _run(["bash", "scripts/deploy.sh"], {"COOLIFY_ENV_FILE": str(_env_file(repo, base))}, cwd=repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "chưa finished" in res.stdout
    assert "✓" not in res.stdout and "✗" not in res.stdout  # không smoke bản cũ


def test_deploy_passes_pushed_commit_to_smoke(stub, repo, tmp_path):
    """deploy.sh đặt SMOKE_EXPECT_VERSION = HEAD đã push; node giả ghi lại env + tham số smoke_e2e.ts nhận được."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    (repo / "realtime" / "node_modules" / "socket.io-client").mkdir(parents=True)
    bin_dir, seen = tmp_path / "bin", tmp_path / "seen.txt"
    bin_dir.mkdir()
    node = bin_dir / "node"
    node.write_text(f'#!/usr/bin/env bash\necho "$SMOKE_EXPECT_VERSION|$*" > "{seen}"\n')
    node.chmod(0o755)
    base = stub(version=head)
    env = {"COOLIFY_ENV_FILE": str(_env_file(repo, base)), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    res = _run(["bash", "scripts/deploy.sh"], env, cwd=repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "✓ web" in res.stdout
    assert seen.read_text().strip() == f"{head}|scripts/smoke_e2e.ts {base} --profile prod"
