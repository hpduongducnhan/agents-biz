"""`scripts/scaffold/new_app.py`: bảng đổi tên theo ngữ cảnh (tên hiển thị, slug, tiền tố, cổng, Redis db), kiểm tham
số, chép bỏ secret / dữ liệu chạy thử, giữ bit thực thi, đổi tên file. Không cần hạ tầng."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("new_app", REPO / "scripts" / "scaffold" / "new_app.py")
na = importlib.util.module_from_spec(spec)
sys.modules["new_app"] = na
spec.loader.exec_module(na)

APP = na.App("Task Hub", "taskhub", "th", "83", (13, 14, 15))


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('SIGNATURE = "X-BizWithAgents-Signature"', 'SIGNATURE = "X-TaskHub-Signature"'),
        ('PROJECT_NAME: str = "BizWithAgents"', 'PROJECT_NAME: str = "Task Hub"'),
        ("GET /bizwithagents/api/tasks/list", "GET /taskhub/api/tasks/list"),
        ("DB bizwithagents_test", "DB taskhub_test"),
        ("rkey → bw:agentcfg:v", "rkey → th:agentcfg:v"),
        ('localStorage "bw.assistant.view"', 'localStorage "th.assistant.view"'),
        ("service bw-api", "service th-api"),
        ("key bw_refresh_token", "key th_refresh_token"),
        ("poetry run bw api --reload", "poetry run th api --reload"),
        ('LOGGER_NAME = "bw"', 'LOGGER_NAME = "th"'),
        ("chạy `bw keys`", "chạy `th keys`"),
        ("abw:x bwx rainbow bwlike", "abw:x bwx rainbow bwlike"),  # không trúng từ khác
        ("web :8201 · api 8202 · rt 8203 · 8204", "web :8301 · api 8302 · rt 8303 · 8304"),
        ("fake llm 8799 · infra 15432 · 82010", "fake llm 8899 · infra 15532 · 82010"),
        ("127.0.0.1:16379 · 5673:5672 · 15673:15672 · 27018", "127.0.0.1:16479 · 5773:5672 · 15773:15672 · 27118"),
        ("container 16811–16813", "container 16831–16833"),
        ("REDIS_RW_URL=redis://127.0.0.1:6379/10", "REDIS_RW_URL=redis://127.0.0.1:6379/13"),
        ("compose redis://127.0.0.1:16379/10", "compose redis://127.0.0.1:16479/13"),
        ('TEST_REDIS_DB = "11"', 'TEST_REDIS_DB = "14"'),
        ("REDIS_DB = 12  # dev / prod 10, test 11 (D19)", "REDIS_DB = 15  # dev / prod 13, test 14 (D19)"),
        ("Redis db 12, stack thử; db 10 dev", "Redis db 15, stack thử; db 13 dev"),
    ],
)
def test_rewrite_rules(before, after):
    assert na.rewrite(before, na.rules(APP)) == after


def test_local_ports_differ_per_app_and_never_collide():
    seen: dict[int, str] = {}
    for ports in range(10, 100):
        app = na.App("Q", "qapp", "qa", str(ports), (1, 2, 3))
        mapped = [int(na.rewrite(str(port), na.rules(app))) for port in na.LOCAL_PORTS]
        assert all(1024 < m < 65536 for m in mapped), ports
        for m in mapped:
            assert m not in seen, f"PORTS={ports} trùng {seen[m]}"
            seen[m] = f"PORTS={ports}"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"slug": "bizwithagents"}, "SLUG"),
        ({"slug": "Bad"}, "SLUG"),
        ({"prefix": "bw"}, "PREFIX"),
        ({"prefix": "toolong"}, "PREFIX"),
        ({"ports": "82"}, "PORTS"),
        ({"ports": "8"}, "PORTS"),
        ({"redis": (10, 21, 22)}, "REDIS_DBS"),
        ({"redis": (20, 20, 22)}, "REDIS_DBS"),
        ({"name": "!!!"}, "NAME"),
    ],
)
def test_validate_rejects(tmp_path, override, message):
    fields = {"name": "Task Hub", "slug": "taskhub", "prefix": "th", "ports": "83", "redis": (13, 14, 15)} | override
    with pytest.raises(SystemExit, match=message):
        na.validate(na.App(**fields), tmp_path / "new")


def test_validate_rejects_existing_dest(tmp_path):
    with pytest.raises(SystemExit, match="DEST"):
        na.validate(APP, tmp_path)


def test_copy_skips_secrets_keeps_exec_bit_and_renames(tmp_path):
    src = tmp_path / "src"
    (src / "scripts").mkdir(parents=True)
    (src / ".git").mkdir()
    (src / ".secrets").mkdir()
    (src / "frontend/node_modules/x").mkdir(parents=True)
    (src / ".env").write_text("SECRET=1", encoding="utf-8")
    (src / ".secrets/k.pem").write_text("k", encoding="utf-8")
    (src / ".git/HEAD").write_text("ref", encoding="utf-8")
    run = src / "scripts/run.sh"
    run.write_text("#!/bin/sh\npoetry run bw api # bizwithagents\n", encoding="utf-8")
    run.chmod(0o755)
    (src / "deploy").mkdir()
    (src / "deploy/bizwithagents.conf").write_text("bw:x", encoding="utf-8")
    (src / "icon.png").write_bytes(bytes([0x89, 0x50, 0x4E, 0x47, 0xFF, 0xFE]))
    dest = tmp_path / "dest"
    files = na.copy_tree(src, dest)
    names = {p.relative_to(dest).as_posix() for p in files}
    assert names == {"scripts/run.sh", "deploy/bizwithagents.conf", "icon.png"}
    changed, moved = na.rename(dest, APP)
    assert (changed, moved) == (2, 1)
    assert (dest / "scripts/run.sh").read_text(encoding="utf-8") == "#!/bin/sh\npoetry run th api # taskhub\n"
    assert os.access(dest / "scripts/run.sh", os.X_OK)
    assert (dest / "deploy/taskhub.conf").read_text(encoding="utf-8") == "th:x"
    assert (dest / "icon.png").read_bytes()[:4] == b"\x89PNG"


MAKEFILE = """.PHONY: api new-module setup new-app new-app-check init-app

api:
\tpoetry run bw api
new-app:\t## tạo app
\tpython new_app.py --dest $(DEST)
new-app-check:
\tscripts/scaffold/check_app.sh

init-app:\t## tại chỗ
\tpython new_app.py --in-place \\
\t\t--ports $(PORTS)
setup:
\tpython3 scripts/setup_env.py # bizwithagents
"""


def test_strip_template_targets_keeps_the_rest(tmp_path):
    (tmp_path / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    na.strip_template_targets(tmp_path)
    text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert ".PHONY: api new-module setup\n" in text
    assert "new_app.py" not in text and "check_app" not in text and "--ports" not in text
    assert "api:\n\tpoetry run bw api" in text and "setup:\n\tpython3 scripts/setup_env.py" in text


def test_tree_skips_vcs_deps_env_and_symlinks(tmp_path):
    for rel in (".git/config", "backend/.venv/bin/bw", "frontend/node_modules/x/i.js", "src/a.py", ".env", "debug/x"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("bw", encoding="utf-8")
    (tmp_path / "link").symlink_to(tmp_path / "src/a.py")
    dirs, files = na.tree(tmp_path)
    assert {p.relative_to(tmp_path).as_posix() for p in files} == {"src/a.py"}
    assert {p.relative_to(tmp_path).as_posix() for p in dirs} == {"backend", "frontend", "src"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def fake_clone(root: Path) -> Path:
    """Bản clone template tối thiểu: Makefile, công cụ chỉ của template, skill, .env + .venv (không được đụng)."""
    files = {
        "Makefile": MAKEFILE,
        "README.md": "# BizWithAgents\npoetry run bw migrate · DB bizwithagents · cổng 8201\n",
        "scripts/scaffold/new_app.py": "x",
        "scripts/scaffold/check_app.sh": "x",
        "scripts/tests/test_new_app.py": "x",
        ".agents/skills/new-app/SKILL.md": "x",
        ".agents/skills/setup-env/SKILL.md": "make setup # bizwithagents\n",
        ".claude/skills/new-app/SKILL.md": "x",
        ".gitignore": ".env\n.venv/\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "qa@test.local")
    git(root, "config", "user.name", "QA")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "template")
    git(root, "remote", "add", "origin", "https://example.invalid/bizwithagents.git")
    (root / ".env").write_text("POSTGRES_RW_URL=postgresql://bizwithagents\n", encoding="utf-8")
    (root / "backend/.venv/bin").mkdir(parents=True)
    (root / "backend/.venv/bin/bw").write_text("bizwithagents", encoding="utf-8")
    return root


def test_in_place_renames_commits_and_keeps_template_remote(tmp_path, monkeypatch, capsys):
    root = fake_clone(tmp_path / "taskhub")
    monkeypatch.setattr(na, "reformat", lambda dest: None)
    argv = ["--in-place", "--src", str(root), "--name", "Task Hub", "--slug", "taskhub", "--prefix", "th"]
    assert na.main([*argv, "--ports", "83", "--redis-dbs", "13,14,15"]) == 0
    assert (root / "README.md").read_text(
        encoding="utf-8"
    ) == "# Task Hub\npoetry run th migrate · DB taskhub · cổng 8301\n"
    assert (root / ".agents/skills/setup-env/SKILL.md").read_text(encoding="utf-8") == "make setup # taskhub\n"
    for rel in sorted(na.TEMPLATE_ONLY - {"scripts/tests/test_new_app.py"}) + ["scripts/tests/test_new_app.py"]:
        assert not (root / rel).exists(), rel
    assert "init-app" not in (root / "Makefile").read_text(encoding="utf-8")
    assert (root / ".env").read_text(encoding="utf-8") == "POSTGRES_RW_URL=postgresql://bizwithagents\n"
    assert (root / "backend/.venv/bin/bw").read_text(encoding="utf-8") == "bizwithagents"
    assert git(root, "remote").split() == ["template"]
    assert git(root, "log", "-1", "--format=%s").strip() == "chore: tạo Task Hub từ template BizWithAgents"
    assert git(root, "status", "--porcelain") == ""
    out = capsys.readouterr().out
    assert (
        "remote origin → template" in out
        and ".env có sẵn không đổi" in out
        and "`make setup SUPERADMIN=<email> VERIFY=1`" in out
    )


@pytest.mark.parametrize(
    ("prepare", "message"),
    [
        (lambda root: (root / "README.md").write_text("đổi", encoding="utf-8"), "chưa commit"),
        (lambda root: (root / "Makefile").write_text("đã đổi tên", encoding="utf-8"), "đã đổi tên rồi"),
    ],
)
def test_in_place_refuses_dirty_or_renamed_tree(tmp_path, prepare, message):
    root = fake_clone(tmp_path / "taskhub")
    prepare(root)
    with pytest.raises(SystemExit, match=message):
        na.main(["--in-place", "--src", str(root), "--name", "T H", "--slug", "taskhub", "--prefix", "th",
                 "--ports", "83", "--redis-dbs", "13,14,15"])  # fmt: skip


def test_in_place_refuses_the_template_checkout_itself(tmp_path):
    root = fake_clone(tmp_path / "BizWithAgents")
    problems = na.in_place_problems(root)
    assert len(problems) == 1 and "bản template" in problems[0]
    assert (root / "scripts/scaffold/new_app.py").exists()


def test_copy_mode_needs_dest(tmp_path):
    with pytest.raises(SystemExit, match="--dest"):
        na.main(["--name", "T H", "--slug", "taskhub", "--prefix", "th", "--ports", "83", "--redis-dbs", "13,14,15"])
