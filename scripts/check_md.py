"""Kiểm luật tài liệu (R2, R25) cho `CLAUDE.md` + `.claude/**/*.md`.

- Mỗi file tối đa 500 dòng.
- Dòng không trống đầu tiên sau H1 là `> **Backlinks:**`, có link về `CLAUDE.md` gốc; file trong package
  (thư mục có `README.md`) còn phải link về `README.md` đó.
- Link tương đối (ngoài code) trỏ tới file có thật.
- Mọi file tới được từ `CLAUDE.md` gốc qua link (không file mồ côi).

Chạy: `python3 scripts/check_md.py` → exit 1 kèm danh sách lỗi nếu vi phạm.
"""

from __future__ import annotations

import re
import sys
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT_DOC = REPO / "CLAUDE.md"
DOCS = REPO / ".claude"
SKIP_DIRS = {"assets", "worktrees", "skills"}  # worktree của agent; skill Claude Code (có frontmatter)
MAX_LINES = 500
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def md_files() -> list[Path]:
    files = [p for p in DOCS.rglob("*.md") if not SKIP_DIRS & set(p.relative_to(DOCS).parts)]
    return [ROOT_DOC, *sorted(files)]


def prose_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Dòng ngoài code fence, đã bỏ inline code — chỉ ở đây mới tính link."""
    out, fence = [], None
    for no, line in enumerate(lines, start=1):
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                continue
            out.append((no, INLINE_CODE_RE.sub("", line)))
        elif m and set(line.strip()) <= {fence[0]} and len(line.strip()) >= len(fence):
            fence = None
    return out


def local_targets(path: Path, lines: list[str]) -> list[tuple[int, str, Path]]:
    found = []
    for no, line in prose_lines(lines):
        for target in LINK_RE.findall(line):
            if SCHEME_RE.match(target) or target.startswith(("#", "/")):
                continue
            rel = target.split("#", 1)[0]
            if rel:
                found.append((no, target, (path.parent / rel).resolve()))
    return found


def check_backlinks(path: Path, lines: list[str], targets: list[tuple[int, str, Path]]) -> list[str]:
    rel = path.relative_to(REPO).as_posix()
    if not lines or not lines[0].startswith("# "):
        return [f"{rel}: dòng 1 phải là H1"]
    after = next(((i, ln) for i, ln in enumerate(lines[1:], start=2) if ln.strip()), (0, ""))
    if not after[1].startswith("> **Backlinks:**"):
        return [f"{rel}: thiếu `> **Backlinks:**` ngay sau H1"]
    linked = {dst for no, _, dst in targets if no == after[0]}
    problems = []
    if ROOT_DOC.resolve() not in linked:
        problems.append(f"{rel}:{after[0]}: Backlinks thiếu link về CLAUDE.md")
    readme = path.parent / "README.md"
    if path.name != "README.md" and readme.exists() and readme.resolve() not in linked:
        problems.append(f"{rel}:{after[0]}: Backlinks thiếu link về README.md của package")
    return problems


def main() -> int:
    problems: list[str] = []
    graph: dict[Path, set[Path]] = {}
    files = md_files()
    for path in files:
        rel = path.relative_to(REPO).as_posix()
        lines = path.read_text(encoding="utf-8").split("\n")
        count = len(lines) - (1 if lines[-1] == "" else 0)
        if count > MAX_LINES:
            problems.append(f"{rel}: {count} dòng > {MAX_LINES} — tách thành package (R25)")
        targets = local_targets(path, lines)
        for no, target, dst in targets:
            if not dst.exists():
                problems.append(f"{rel}:{no}: link hỏng `{target}`")
        if path != ROOT_DOC:
            problems += check_backlinks(path, lines, targets)
        graph[path.resolve()] = {dst for _, _, dst in targets if dst.suffix == ".md"}

    seen, queue = {ROOT_DOC.resolve()}, deque([ROOT_DOC.resolve()])
    while queue:
        for nxt in graph.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    problems += [
        f"{p.relative_to(REPO).as_posix()}: mồ côi — không link nào từ CLAUDE.md dẫn tới"
        for p in files
        if p.resolve() not in seen
    ]

    for line in problems:
        print(line)
    print(f"check_md: {len(files)} file, {len(problems)} lỗi")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
