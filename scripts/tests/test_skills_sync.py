"""Skill dùng chung (D26): `.claude/skills/` là bản sao y hệt `.agents/skills/`; repo thật phải khớp."""

from __future__ import annotations

import skills_sync as ss


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_sync_adds_updates_and_removes_then_check_passes(tmp_path):
    write(tmp_path / ".agents/skills/a/SKILL.md", "a2")
    write(tmp_path / ".agents/skills/b/SKILL.md", "b")
    write(tmp_path / ".claude/skills/a/SKILL.md", "a1")
    write(tmp_path / ".claude/skills/old/SKILL.md", "x")
    assert ss.problems(tmp_path) == [
        "thiếu: .claude/skills/b/SKILL.md",
        "lệch: .claude/skills/a/SKILL.md",
        "thừa: .claude/skills/old/SKILL.md (không có bản gốc ở .agents/skills)",
    ]
    assert sorted(ss.sync(tmp_path)) == ["a/SKILL.md", "b/SKILL.md", "old/SKILL.md"]
    assert ss.problems(tmp_path) == []
    assert not (tmp_path / ".claude/skills/old").exists()
    assert ss.main(["--root", str(tmp_path), "--check"]) == 0


def test_check_fails_on_drift(tmp_path, capsys):
    write(tmp_path / ".agents/skills/a/SKILL.md", "a")
    assert ss.main(["--root", str(tmp_path), "--check"]) == 1
    assert "make skills-sync" in capsys.readouterr().err
    assert ss.main(["--root", str(tmp_path)]) == 0
    assert (tmp_path / ".claude/skills/a/SKILL.md").read_text(encoding="utf-8") == "a"


def test_repo_skills_are_in_sync_and_have_frontmatter():
    assert ss.problems() == []
    for name, data in ss.files(ss.ROOT / ss.SRC).items():
        if name.endswith("SKILL.md"):
            head = data.decode().split("---")[1]
            assert f"name: {name.split('/')[0]}" in head and "description: " in head, name
