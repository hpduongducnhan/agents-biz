"""`scripts/scaffold/template_sync.py`: kéo bản sửa của template về app đã đổi tên — dòng template sửa nhận tên app,
file mới mang tên app, phần app tự sửa giữ nguyên, xung đột chỉ khi cùng sửa một dòng. Repo git nhỏ, không hạ tầng."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "scaffold" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


na = _load("new_app")
ts = _load("template_sync")


def readme(title: str, cmd: str, note: str = "ghi chú") -> str:
    return f"# {title}\n{cmd}\n\n## Mục\n\n{note}\n"


TEMPLATE_FILES = {
    "Makefile": ".PHONY: api new-app new-app-check init-app\n\napi:\n\tpoetry run bw api # bizwithagents\n",
    "README.md": readme("BizWithAgents", "poetry run bw migrate · DB bizwithagents · cổng 8201"),
    "scripts/scaffold/new_app.py": "x\n",
    ".gitignore": ".env\n.venv/\ndebug/\n",
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(root: Path, files: dict[str, str], message: str) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def identity(root: Path) -> None:
    git(root, "config", "user.email", "qa@test.local")
    git(root, "config", "user.name", "QA")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """(template, app): template thật (thư mục BizWithAgents) → clone `taskhub` → init-app tại chỗ."""
    monkeypatch.setattr(na, "reformat", lambda dest: None)
    monkeypatch.setattr(ts, "reformat", lambda dest: None)
    template = tmp_path / "BizWithAgents"
    template.mkdir()
    git(template, "init", "-q", "-b", "main")
    identity(template)
    commit(template, TEMPLATE_FILES, "template")
    app = tmp_path / "taskhub"
    git(tmp_path, "clone", "-q", str(template), str(app))
    identity(app)
    argv = ["--in-place", "--src", str(app), "--name", "Task Hub", "--slug", "taskhub", "--prefix", "th"]
    assert na.main([*argv, "--ports", "83", "--redis-dbs", "13,14,15"]) == 0
    return template, app


def sync(app: Path) -> int:
    git(app, "fetch", "-q", "template")
    return ts.sync(app, "template/main", app / "debug/template-sync/work")


def app_file(app: Path) -> dict:
    return json.loads((app / ".template.json").read_text(encoding="utf-8"))


def test_init_app_records_params_and_template_commit(repos):
    template, app = repos
    assert app_file(app) == {
        "name": "Task Hub",
        "slug": "taskhub",
        "prefix": "th",
        "ports": "83",
        "redis_dbs": [13, 14, 15],
        "template_commit": git(template, "rev-parse", "HEAD"),
    }
    assert git(app, "status", "--porcelain") == ""


def test_sync_renames_template_changes_and_keeps_app_changes(repos, capsys):
    template, app = repos
    commit(
        app,
        {"README.md": readme("Task Hub", "poetry run th migrate · DB taskhub · cổng 8301", "ghi chú app")},
        "app",
    )
    commit(
        template,
        {
            "README.md": readme("BizWithAgents", "poetry run bw migrate --check · DB bizwithagents · cổng 8201"),
            "docs/bizwithagents-cache.md": "Redis bw:cache · DB bizwithagents_test · BIZWITHAGENTS_ENV\n",
            "scripts/scaffold/new_app.py": "y\n",
        },
        "template: sửa",
    )
    assert sync(app) == 0
    assert (app / "README.md").read_text(encoding="utf-8") == (
        "# Task Hub\npoetry run th migrate --check · DB taskhub · cổng 8301\n\n## Mục\n\nghi chú app\n"
    )
    assert (app / "docs/taskhub-cache.md").read_text(encoding="utf-8") == (
        "Redis th:cache · DB taskhub_test · TASKHUB_ENV\n"
    )
    assert not (app / "scripts/scaffold/new_app.py").exists()
    assert app_file(app)["template_commit"] == git(template, "rev-parse", "HEAD")
    assert git(app, "status", "--porcelain") == ""
    assert git(app, "log", "-1", "--format=%s").startswith("chore: đồng bộ template ")
    assert not (app / "debug/template-sync/work").exists()
    assert "✓ đồng bộ template" in capsys.readouterr().out
    assert sync(app) == 0
    assert "không có gì để kéo" in capsys.readouterr().out


def test_sync_conflict_only_where_both_sides_edit_the_same_line(repos, capsys):
    template, app = repos
    commit(app, {"README.md": readme("Task Hub", "make api · DB taskhub · cổng 8301")}, "app")
    commit(template, {"README.md": readme("BizWithAgents", "make migrate · DB bizwithagents · cổng 8201")}, "t")
    assert sync(app) == 1
    out = capsys.readouterr().out
    assert "xung đột ở 1 file" in out and "README.md" in out and "git cherry-pick --continue" in out
    assert (app / ".git/CHERRY_PICK_HEAD").exists()
    assert "make migrate · DB taskhub · cổng 8301" in (app / "README.md").read_text(encoding="utf-8")
    assert app_file(app)["template_commit"] == git(template, "rev-parse", "HEAD")
    with pytest.raises(SystemExit, match="đang dở"):
        ts.sync(app, "template/main", app / "debug/template-sync/work")


def test_sync_template_only_change_just_moves_the_pointer(repos, capsys):
    template, app = repos
    commit(template, {"scripts/scaffold/new_app.py": "z\n"}, "template: công cụ")
    head = git(app, "rev-parse", "HEAD")
    assert sync(app) == 0
    assert "không có thay đổi nào cho app" in capsys.readouterr().out
    assert git(app, "diff", "--name-only", head, "HEAD") == ".template.json"


@pytest.mark.parametrize(
    ("prepare", "message"),
    [
        (lambda app: (app / "README.md").write_text("dở", encoding="utf-8"), "chưa commit"),
        (lambda app: (app / ".template.json").unlink(), "thiếu .template.json"),
    ],
)
def test_sync_refuses_dirty_tree_or_missing_app_file(repos, prepare, message):
    template, app = repos
    commit(template, {"README.md": "# BizWithAgents\n"}, "t")
    prepare(app)
    with pytest.raises(SystemExit, match=message):
        sync(app)


def test_sync_refuses_unknown_base_commit(repos):
    template, app = repos
    data = app_file(app) | {"template_commit": "0" * 40}
    commit(app, {".template.json": json.dumps(data)}, "app: sai commit")
    with pytest.raises(SystemExit, match="git fetch template"):
        sync(app)


def test_leftovers_reports_files_still_named_after_the_template(repos):
    _, app = repos
    commit(app, {"a.md": "DB bizwithagents\n", "b.md": "rainbow bwx\n", "c.md": "`bw keys`\n"}, "app")
    assert ts.leftovers(app, "HEAD") == ["a.md", "c.md"]
