"""scripts/secrets_scan.sh trên repo git tạm, gitleaks giả — bước tên riêng (file đang track + lịch sử), mã thoát."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "secrets_scan.sh"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@x.io",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@x.io",
}
HISTORY = "lịch sử git (số dòng"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env={**os.environ, **GIT_ENV})


@pytest.fixture
def repo(tmp_path):
    """Repo tạm có script + một commit sạch; `bin/` chứa gitleaks giả ghi tham số vào `gitleaks.log`."""
    work = tmp_path / "app"
    (work / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, work / "scripts" / "secrets_scan.sh")
    (work / "README.md").write_text("template sạch\n")
    _git(work, "init", "-q", "-b", "main")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "init")
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "gitleaks").write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/gitleaks.log"\nexit ${{GITLEAKS_RC:-0}}\n')
    (stub / "gitleaks").chmod(0o755)
    return work


def _scan(repo: Path, terms: str | None, env: dict | None = None) -> subprocess.CompletedProcess:
    terms_file = repo.parent / "private-terms.txt"
    if terms is not None:
        terms_file.write_text(terms)
    path = f"{repo.parent / 'bin'}:/usr/bin:/bin"  # không có trufflehog — bước đó bỏ qua
    full = {**os.environ, "PATH": path, "PRIVATE_TERMS_FILE": str(terms_file), **(env or {})}
    return subprocess.run(
        ["bash", "scripts/secrets_scan.sh"], cwd=repo, env=full, capture_output=True, text=True, timeout=30
    )


def test_clean_repo_passes_and_runs_gitleaks_on_history_and_uncommitted(repo):
    res = _scan(repo, "# chú thích\nTenRieng\n\n")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "secrets-scan: sạch ✓" in res.stdout and "1 mục" in res.stdout
    calls = (repo.parent / "gitleaks.log").read_text().splitlines()
    assert calls[0].startswith("git --log-opts=--all --redact")
    assert any("--pre-commit --staged" in c for c in calls)
    assert any(c.startswith("git --pre-commit --redact") for c in calls)


def test_private_term_in_tracked_file_fails_case_insensitive(repo):
    (repo / "docs.md").write_text("dòng 1\nchép từ tenrieng-pet\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "docs")
    res = _scan(repo, "TenRieng\n")
    assert res.returncode == 1
    assert "docs.md:2:tenrieng" in res.stdout
    assert "docs.md" in res.stdout.split(HISTORY)[1]
    assert "CÓ PHÁT HIỆN" in res.stderr


def test_private_term_only_in_history_still_fails(repo):
    (repo / "old.md").write_text("server 10.9.8.7\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add")
    _git(repo, "rm", "-q", "old.md")
    _git(repo, "commit", "-q", "-m", "remove")
    res = _scan(repo, "10.9.8.7\n")
    assert res.returncode == 1
    assert "file đang track (số lần" not in res.stdout
    history = res.stdout.split(HISTORY)[1]
    assert history.count("old.md") == 2  # dòng thêm + dòng xoá ở hai commit


def test_missing_terms_file_skips_step_with_defaults_applied(repo):
    res = _scan(repo, None)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "DEFAULTS_APPLIED=[private_terms]" in res.stderr


def test_gitleaks_finding_fails(repo):
    res = _scan(repo, None, {"GITLEAKS_RC": "1"})
    assert res.returncode == 1 and "CÓ PHÁT HIỆN" in res.stderr


def test_no_gitleaks_and_no_docker_exits_2(repo, tmp_path):
    only = tmp_path / "only"
    only.mkdir()
    for tool in ("dirname", "mktemp", "rm"):
        (only / tool).symlink_to(shutil.which(tool))
    res = subprocess.run(
        ["/bin/bash", "scripts/secrets_scan.sh"], cwd=repo, env={"PATH": str(only)}, capture_output=True, text=True
    )
    assert res.returncode == 2 and "cần gitleaks" in res.stderr
