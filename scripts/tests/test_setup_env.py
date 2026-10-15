"""`make setup` (D28): `.env` theo chế độ, khoá bền, không ghi đè cấu hình có sẵn, thứ tự bước, dừng đúng chỗ."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
import setup_env as se

EXAMPLE = """# đầu file
POSTGRES_RW_URL=postgresql+psycopg://<user>:<mật khẩu>@127.0.0.1:5432/app
# compose: POSTGRES_RW_URL=postgresql+psycopg://app:app-dev@127.0.0.1:15432/app
REDIS_RW_URL=redis://127.0.0.1:6379/10
# compose: REDIS_RW_URL=redis://127.0.0.1:16379/10
SUPERADMIN_EMAILS=superadmin@test.local
CREDENTIAL_KEYS=
"""


def test_build_env_local_uses_compose_lines_shared_keeps_placeholders():
    local = se.build_env(EXAMPLE, "local")
    assert "POSTGRES_RW_URL=postgresql+psycopg://app:app-dev@127.0.0.1:15432/app\n" in local
    assert "REDIS_RW_URL=redis://127.0.0.1:16379/10\n" in local
    assert se.placeholders(local) == []
    shared = se.build_env(EXAMPLE, "shared")
    assert se.placeholders(shared) == ["POSTGRES_RW_URL"]  # dòng `# compose:` là chú thích, không tính


def test_ensure_env_creates_file_with_key_and_superadmin_without_printing_values(tmp_path, capsys):
    example, env = tmp_path / ".env.example", tmp_path / ".env"
    example.write_text(EXAMPLE, encoding="utf-8")
    done = se.ensure_env(env, example, "local", "Owner@Example.com")
    assert done == ["tạo .env từ .env.example (MODE=local)", "sinh CREDENTIAL_KEYS", "thêm SUPERADMIN_EMAILS"]
    text = env.read_text(encoding="utf-8")
    key = se.env_value(text, "CREDENTIAL_KEYS")
    assert key and len(key) == 44 and key.endswith("=")  # khoá Fernet: 32 byte base64 urlsafe
    assert se.env_value(text, "SUPERADMIN_EMAILS") == "superadmin@test.local,Owner@Example.com"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert key not in capsys.readouterr().out


def test_ensure_env_rerun_keeps_existing_values(tmp_path):
    example, env = tmp_path / ".env.example", tmp_path / ".env"
    example.write_text(EXAMPLE, encoding="utf-8")
    env.write_text(
        "POSTGRES_RW_URL=postgresql+psycopg://mine@db/app\nSUPERADMIN_EMAILS=superadmin@test.local\nCREDENTIAL_KEYS=keep\n",
        encoding="utf-8",
    )
    assert se.ensure_env(env, example, "local", "superadmin@TEST.local") == []  # có sẵn → không đổi gì
    assert se.ensure_env(env, example, "local", "b@x.io") == ["thêm SUPERADMIN_EMAILS"]
    text = env.read_text(encoding="utf-8")
    assert "POSTGRES_RW_URL=postgresql+psycopg://mine@db/app" in text and "CREDENTIAL_KEYS=keep" in text
    assert se.env_value(text, "SUPERADMIN_EMAILS") == "superadmin@test.local,b@x.io"


@pytest.mark.parametrize(
    ("text", "parsed"),
    [("v22.21.1\n", (22, 21, 1)), ("Poetry (version 2.3.2)", (2, 3, 2)), ("Python 3.13", (3, 13)), ("?", ())],
)
def test_version(text, parsed):
    assert se.version(text) == parsed


def test_tool_problems_lists_missing_tools_old_node_and_docker_only_in_local_mode():
    def which(name):
        return None if name in {"poetry", "docker"} else f"/usr/bin/{name}"

    def output(cmd):
        return "v20.11.0" if cmd[0] == "node" else ""

    local = se.tool_problems("local", which=which, output=output)
    assert [p.split(" ")[0] + " " + p.split(" ")[1] for p in local] == ["thiếu poetry", "Node 20.11.0", "thiếu Docker"]
    assert not any("Docker" in p for p in se.tool_problems("shared", which=which, output=output))


def test_busy_ports_reports_open_ones():
    assert se.busy_ports({"Postgres": 1, "Redis": 2}, connect=lambda port: port == 2) == ["Redis 2"]


class FakeRun:
    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, cmd, label):
        self.calls.append(" ".join(cmd[1:]))
        return 1 if self.fail and self.fail in " ".join(cmd) else 0


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    monkeypatch.setattr(se, "ROOT", tmp_path)
    return tmp_path


def setup(run, mode="local", verify=False, install=True):
    return se.Setup(mode, None, verify, install, run=run)


def test_local_flow_runs_every_step_in_order(repo):
    run = FakeRun()
    code = setup(run, verify=True).main(tools=lambda m: [], ports=lambda p: [], running=lambda: False)
    assert code == 0
    assert run.calls == [
        "be-install", "rt-install", "fe-install", "keys", "infra-up", "check-config", "migrate",
        "dev-up MONGO=on", "smoke-local MONGO=on",
    ]  # fmt: skip
    assert (repo / ".env").exists()


def test_stops_on_missing_tools_before_touching_anything(repo, capsys):
    run = FakeRun()
    assert setup(run).main(tools=lambda m: ["thiếu poetry — cài"], ports=lambda p: [], running=lambda: False) == 1
    assert run.calls == [] and not (repo / ".env").exists()
    assert "✗ thiếu poetry" in capsys.readouterr().out


def test_shared_mode_stops_until_owner_fills_passwords(repo, capsys):
    run = FakeRun()
    assert (
        setup(run, mode="shared", install=False).main(tools=lambda m: [], ports=lambda p: [], running=lambda: True) == 1
    )
    assert run.calls == ["keys"]
    assert "POSTGRES_RW_URL" in capsys.readouterr().out


def test_busy_infra_ports_stop_local_mode_unless_own_infra_runs(repo, capsys):
    run = FakeRun()
    busy = setup(run, install=False).main(tools=lambda m: [], ports=lambda p: ["Postgres 15432"], running=lambda: False)
    assert busy == 1 and "infra-up" not in run.calls and "cổng đang bận" in capsys.readouterr().out
    run = FakeRun()
    ok = setup(run, install=False).main(tools=lambda m: [], ports=lambda p: ["Postgres 15432"], running=lambda: True)
    assert ok == 0 and "infra-up" in run.calls


def test_failed_step_stops_the_rest(repo):
    run = FakeRun(fail="migrate")
    assert setup(run, install=False).main(tools=lambda m: [], ports=lambda p: [], running=lambda: False) == 1
    assert run.calls[-1] == "migrate"


def test_shell_logs_output_and_shows_tail_on_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(se, "ROOT", tmp_path)
    monkeypatch.setattr(se, "LOG", tmp_path / "debug/setup.log")
    assert se.shell(["sh", "-c", "echo ok-line"], "thử") == 0
    assert se.shell(["sh", "-c", "echo bad-line; exit 3"], "hỏng") == 3
    log = Path(tmp_path / "debug/setup.log").read_text(encoding="utf-8")
    assert "=== thử" in log and "ok-line" in log and "bad-line" in log
    out = capsys.readouterr().out
    assert "bad-line" in out and "ok-line" not in out


def test_main_tools_only_reports(monkeypatch, capsys):
    monkeypatch.setattr(se, "tool_problems", lambda mode: ["thiếu docker — cài"])
    assert se.main(["--tools-only"]) == 1
    monkeypatch.setattr(se, "tool_problems", lambda mode: [])
    assert se.main(["--tools-only", "--mode", "shared"]) == 0
    assert "thiếu docker" in capsys.readouterr().out
