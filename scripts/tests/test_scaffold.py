"""`scripts/scaffold/new_module.py`: tính mã lỗi / tiền tố `loc` / revision kế tiếp, sinh đủ file (đổi token), chèn một
dòng đăng ký ở 6 chỗ lõi, chạy lại không nhân đôi, từ chối tên sai / module đã có. Không cần hạ tầng."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("new_module", REPO / "scripts" / "scaffold" / "new_module.py")
nm = importlib.util.module_from_spec(spec)
sys.modules["new_module"] = nm  # dataclass cần module có trong sys.modules
spec.loader.exec_module(nm)

CORE_FILES = (
    "backend/app/domains.py",
    "backend/app/core/errors.py",
    "backend/app/core/logging.py",
    "backend/app/models/__init__.py",
    "frontend/src/modules/registry.ts",
    "frontend/src/lib/api/endpoints.ts",
)


@pytest.fixture
def repo(tmp_path) -> Path:
    for rel in CORE_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, tmp_path / rel)
    shutil.copytree(REPO / "backend/migrations/versions", tmp_path / "backend/migrations/versions")
    return tmp_path


def test_plan_picks_next_code_loc_and_revision(repo):
    s = nm.plan(repo, "zz_notes", "Ghi chú", "Notes")
    tip, top = nm.head(repo / "backend/migrations/versions")
    assert (s.code % 100, s.code >= 10100) == (0, True)  # sau dải của Tasks
    taken = set(nm.re.findall(r'"([a-z]{2,6})"', (repo / "backend/app/core/logging.py").read_text(encoding="utf-8")))
    assert "zznotes".startswith(s.loc) and s.loc not in taken
    assert s.rev == f"{top + 1:04d}_zz_notes" and s.down_rev == tip
    assert nm.loc_prefix("tasks", '"tas" "task"') == "tasks"


@pytest.mark.parametrize("bad", ["Notes", "1x", "a", "tasks", "agent", "has-dash", "x" * 40])
def test_rejects_bad_or_reserved_names(repo, bad):
    with pytest.raises(SystemExit):
        nm.plan(repo, bad, "X", "X")


def test_generate_and_register_once(repo):
    s = nm.plan(repo, "meeting_notes", "Biên bản họp", "Meeting notes")
    written = nm.generate(repo, s)
    rels = {p.relative_to(repo).as_posix() for p in written}
    assert {
        "backend/app/meeting_notes/ops.py",
        "backend/app/meeting_notes/agent.py",
        "backend/app/meeting_notes/prompts/meeting_notes.md",
        f"backend/migrations/versions/{s.rev}.py",
        "backend/tests/meeting_notes/test_ops.py",
        "backend/tests/agent_eval/meeting_notes_vi.yaml",
        "frontend/src/modules/meeting_notes/index.ts",
        "frontend/src/modules/meeting_notes/pages/ListPage.tsx",
        "frontend/test/modules/meeting_notes.test.tsx",
    } <= rels
    for path in written:
        text = path.read_text(encoding="utf-8")
        assert "__mod__" not in text and "__Mod__" not in text and "__title" not in text and "__code" not in text, path
    models = (repo / "backend/app/meeting_notes/models.py").read_text(encoding="utf-8")
    assert "class MeetingNotesItem(TenantScoped, table=True)" in models and '__tablename__ = "meeting_notes"' in models
    assert 'to: "/meeting-notes"' in (repo / "frontend/src/modules/meeting_notes/index.ts").read_text(encoding="utf-8")
    assert sorted(nm.register(repo, s)) == sorted(CORE_FILES)
    assert nm.register(repo, s) == []  # chạy lại không đổi gì
    domains = (repo / "backend/app/domains.py").read_text(encoding="utf-8")
    assert domains.count('"meeting_notes",') == 1
    assert f'"meeting_notes": ({s.code}, {s.code + 99}),' in (repo / "backend/app/core/errors.py").read_text()
    registry = (repo / "frontend/src/modules/registry.ts").read_text(encoding="utf-8")
    assert 'import { meeting_notesModule } from "./meeting_notes";' in registry
    assert ", meeting_notesModule]" in registry and "[tasksModule" in registry
    endpoints = (repo / "frontend/src/lib/api/endpoints.ts").read_text(encoding="utf-8")
    assert '"meeting_notes.list": "GET",' in endpoints and '"meeting_notes.delete": "POST",' in endpoints
    with pytest.raises(SystemExit, match="đã có"):
        nm.generate(repo, s)


def test_second_module_gets_next_range(repo):
    first = nm.plan(repo, "zz_notes", "Ghi chú", "Notes")
    nm.generate(repo, first)
    nm.register(repo, first)
    second = nm.plan(repo, "zz_links", "Liên kết", "Links")
    assert second.code == first.code + 100 and second.down_rev == first.rev
