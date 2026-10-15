"""Sơ đồ archify của trang doc: sinh lại theo khoá hash, kiểm sơ đồ cũ / thiếu / thừa."""

# ruff: noqa: E501 — giữ nguyên docstring dài của bản gốc

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from docsite.common import ARCHIFY, ASSETS, DIAGRAM_TYPES, DIAGRAMS, LOCK, MERMAID_RE, REPO

if TYPE_CHECKING:
    from docsite.render import Site


# ── sơ đồ archify ───────────────────────────────────────────────────────────
def diagram_kind(spec: Path) -> str | None:
    """`flow.workflow.json` trong thư mục `diagrams/` → "workflow"; không phải spec → None."""
    parts = spec.name.split(".")
    if spec.parent.name != DIAGRAMS or len(parts) != 3 or parts[2] != "json" or parts[1] not in DIAGRAM_TYPES:
        return None
    return parts[1]


def diagram_html(spec: Path) -> Path:
    return spec.with_name(spec.name.split(".")[0] + ".html")


def diagram_specs(docs_dir: Path) -> list[Path]:
    return sorted(p for p in docs_dir.rglob(f"{DIAGRAMS}/*.json") if diagram_kind(p))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_lock(docs_dir: Path) -> dict[str, dict[str, str]]:
    path = docs_dir / ASSETS / LOCK
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def archify_runner(cli: str | Path | None = None):
    """`node archify deliver <loại> <spec> <html> --quality showcase` — cần skill archify (hoặc ARCHIFY=<bin/archify.mjs>).
    Chạy ở gốc repo: archify mới bắt `meta.output` tương đối từ thư mục chạy (spec ghi `.claude/<…>/diagrams/<tên>.html`)."""
    path = Path(cli or os.environ.get("ARCHIFY") or ARCHIFY).expanduser()
    if not path.is_file():
        raise SystemExit(
            f"không thấy archify ở {path} — cài skill archify hoặc đặt ARCHIFY=<đường dẫn bin/archify.mjs>"
        )

    def run(kind: str, spec: Path, out: Path) -> None:
        cmd = ["node", str(path), "deliver", kind, str(spec), str(out), "--quality", "showcase", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=REPO)
        if res.returncode != 0:
            raise SystemExit(
                f"archify từ chối {spec.name} (exit {res.returncode}):\n{res.stdout[-6000:]}{res.stderr[-2000:]}"
            )

    return run


def render_diagrams(site: Site, runner=None) -> list[str]:  # noqa: ANN001 — runner(kind, spec, out) để test thay archify
    """Sinh lại sơ đồ có spec / HTML khác khoá; xoá HTML không còn spec; ghi `assets/diagrams.lock.json`."""
    docs = site.dir
    lock = read_lock(docs)
    specs = diagram_specs(docs)
    fresh: dict[str, dict[str, str]] = {}
    done = []
    for spec in specs:
        rel = spec.relative_to(docs).as_posix()
        page = diagram_html(spec)
        entry = lock.get(rel) or {}
        if not (page.is_file() and entry.get("spec") == _sha(spec) and entry.get("html") == _sha(page)):
            runner = runner or archify_runner()
            runner(diagram_kind(spec), spec, page)
            done.append(rel)
        fresh[rel] = {"spec": _sha(spec), "html": _sha(page)}
    wanted = {diagram_html(s) for s in specs}
    for page in docs.rglob(f"{DIAGRAMS}/*.html"):
        if page not in wanted:
            page.unlink()
    if fresh != lock:
        path = docs / ASSETS / LOCK
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return done


def relock_diagrams(site: Site) -> int:
    """Ghi lại khoá theo spec + HTML đang có, không gọi archify — dùng sau khi `make new-app` thay chữ cả spec lẫn HTML.
    Spec chưa có HTML thì bỏ qua (docs-check vẫn báo "chưa sinh"); trả số sơ đồ đã khoá."""
    docs = site.dir
    fresh = {
        s.relative_to(docs).as_posix(): {"spec": _sha(s), "html": _sha(diagram_html(s))}
        for s in diagram_specs(docs)
        if diagram_html(s).is_file()
    }
    if fresh != read_lock(docs):
        path = docs / ASSETS / LOCK
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return len(fresh)


def _diagram_problems(docs_dir: Path) -> list[str]:
    lock = read_lock(docs_dir)
    specs = diagram_specs(docs_dir)
    problems = []
    for spec in specs:
        rel = spec.relative_to(docs_dir).as_posix()
        page, entry = diagram_html(spec), lock.get(rel)
        if entry is None or not page.is_file():
            problems.append(f"sơ đồ chưa sinh: {rel}")
        elif entry.get("spec") != _sha(spec) or entry.get("html") != _sha(page):
            problems.append(f"sơ đồ cũ: {rel}")
    names = {s.relative_to(docs_dir).as_posix() for s in specs}
    problems += [f"khoá thừa: {rel}" for rel in lock if rel not in names]
    wanted = {diagram_html(s) for s in specs}
    problems += [
        f"thừa: {p.relative_to(docs_dir).as_posix()}" for p in docs_dir.rglob(f"{DIAGRAMS}/*.html") if p not in wanted
    ]
    for md in docs_dir.rglob("*.md"):
        if MERMAID_RE.search(md.read_text(encoding="utf-8")):
            problems.append(f"mermaid (dùng archify): {md.relative_to(docs_dir).as_posix()}")
    return problems
