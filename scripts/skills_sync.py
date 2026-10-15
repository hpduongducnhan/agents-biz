"""Skill dùng chung cho mọi agent (D26): bản gốc `.agents/skills/` (Codex, Gemini CLI) → bản sao y hệt
`.claude/skills/` (Claude Code).

`make skills-sync` chép (thêm / sửa / xoá cho khớp) · `make skills-check` (trong `make ci`) báo lệch → exit 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(".agents/skills")
DEST = Path(".claude/skills")


def files(base: Path) -> dict[str, bytes]:
    if not base.is_dir():
        return {}
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def problems(root: Path = ROOT) -> list[str]:
    src, dest = files(root / SRC), files(root / DEST)
    out = [f"thiếu: {DEST / rel}" for rel in src if rel not in dest]
    out += [f"lệch: {DEST / rel}" for rel in src if rel in dest and dest[rel] != src[rel]]
    out += [f"thừa: {DEST / rel} (không có bản gốc ở {SRC})" for rel in dest if rel not in src]
    return out


def sync(root: Path = ROOT) -> list[str]:
    src, dest = files(root / SRC), files(root / DEST)
    changed = []
    for rel, data in src.items():
        if dest.get(rel) != data:
            target = root / DEST / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            changed.append(rel)
    for rel in dest:
        if rel not in src:
            (root / DEST / rel).unlink()
            changed.append(rel)
    for folder in sorted((root / DEST).rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="chỉ kiểm: .claude/skills lệch bản gốc → exit 1")
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    if a.check:
        found = problems(a.root)
        for p in found:
            print(f"✗ {p}", file=sys.stderr)
        if found:
            print("→ sửa ở .agents/skills/ rồi chạy `make skills-sync`", file=sys.stderr)
            return 1
        print(f"✓ skills: {len(files(a.root / SRC))} file khớp giữa {SRC} và {DEST}")
        return 0
    changed = sync(a.root)
    print(f"skills: chép {len(changed)} file" + (f" ({', '.join(changed)})" if changed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
