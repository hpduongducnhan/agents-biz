"""Trang review tài liệu: mỗi `.claude/**/*.md` → `.html` cạnh nó + `.claude/index.html` + dữ liệu sinh trong `assets/`.

Chạy: `make docs` (ghi) · `make docs-check` (CI: HTML / sơ đồ cũ, thiếu, thừa hoặc link hỏng → lỗi) ·
`python scripts/docs_site.py --diagrams` (sinh lại sơ đồ archify đổi rồi ghi) ·
`--relock-diagrams` (khoá lại sơ đồ sau `make new-app`, không cần archify). CSS / JS viết tay ở `.claude/assets/`
(docs.css, docs.js); script sinh `highlight.css`, `search-index.js`, `diagrams.lock.json`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docsite.common import ASSETS, MARK, REPO
from docsite.diagrams import _diagram_problems, relock_diagrams, render_diagrams
from docsite.render import Site


# ── ghi / kiểm ──────────────────────────────────────────────────────────────
def _generated(docs_dir: Path) -> set[Path]:
    return {
        p
        for p in docs_dir.rglob("*.html")
        if p.relative_to(docs_dir).parts[0] != ASSETS and MARK in p.read_text(encoding="utf-8", errors="ignore")
    }


def check(outputs: dict[Path, str], docs_dir: Path) -> list[str]:
    problems = []
    for path, text in outputs.items():
        rel = path.relative_to(docs_dir).as_posix()
        if not path.exists():
            problems.append(f"thiếu: {rel}")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"cũ: {rel}")
    problems += [f"thừa: {p.relative_to(docs_dir).as_posix()}" for p in _generated(docs_dir) - set(outputs)]
    problems += _diagram_problems(docs_dir)
    return sorted(problems)


def write(outputs: dict[Path, str], docs_dir: Path) -> list[Path]:
    changed = []
    for path, text in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            changed.append(path)
    for orphan in _generated(docs_dir) - set(outputs):
        orphan.unlink()
        changed.append(orphan)
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO, help="gốc repo (mặc định: repo này)")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm: HTML cũ / thiếu / thừa hoặc link hỏng → exit 1")
    ap.add_argument(
        "--diagrams", action="store_true", help="sinh lại sơ đồ archify có spec đổi (cần Node + archify) rồi ghi"
    )
    ap.add_argument(
        "--relock-diagrams",
        action="store_true",
        help="khoá lại sơ đồ theo spec + HTML hiện có (sau khi đổi tên bằng thay chữ) — không gọi archify",
    )
    args = ap.parse_args(argv)
    if args.relock_diagrams and not args.check:
        print(f"sơ đồ: khoá lại {relock_diagrams(Site(args.root))}")
    if args.diagrams and not args.check:
        rendered = render_diagrams(Site(args.root))
        print(f"sơ đồ: sinh lại {len(rendered)}" + (f" ({', '.join(rendered)})" if rendered else ""))
    site = Site(args.root)
    outputs = site.build()
    for src, href in site.broken:
        print(f"link hỏng: {src} → {href}", file=sys.stderr)
    if args.check:
        problems = check(outputs, site.dir)
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            print("→ chạy `make docs` rồi commit các file .html", file=sys.stderr)
        return 1 if problems or site.broken else 0
    changed = write(outputs, site.dir)
    print(f"docs: {len(site.docs)} trang · ghi {len(changed)} file · link hỏng {len(site.broken)}")
    return 0
