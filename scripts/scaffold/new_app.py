"""Tạo app mới từ template, đổi tên một lần (D9, D19, D27): tên hiển thị, slug (DB, vhost, đường dẫn
`/<slug>/api`), tiền tố (CLI, Redis `<prefix>:`, exchange `<prefix>.`, service `<prefix>-*`), cổng local 82xx, Redis db
(dev / prod · test · stack thử).

- `make init-app NAME=… SLUG=… PREFIX=… PORTS=… REDIS_DBS=…` (`--in-place`): đổi tên ngay trong bản clone template —
  giữ lịch sử git, remote `origin` → `template`, commit đổi tên.
- `make new-app … DEST=../taskhub`: chép sang thư mục mới (bỏ `.git`, `.env`, `.secrets`, dữ liệu chạy thử)
  + `git init`.

Cả hai giữ bit thực thi, bỏ công cụ chỉ của template, in việc tiếp theo.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {
    ".git", ".secrets", "debug", ".e2e", ".dev-stack", "node_modules", ".venv", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", "dist", "coverage", ".claude-tmp",
}  # fmt: skip
SKIP_FILES = {".env", ".coverage"}
# công cụ chỉ của template (app mới không tạo app khác) — không chép; Makefile bỏ target tương ứng
TEMPLATE_ONLY = {
    "scripts/scaffold/new_app.py",
    "scripts/scaffold/check_app.sh",
    "scripts/scaffold/template_sync.py",
    "scripts/tests/test_new_app.py",
    "scripts/tests/test_template_sync.py",
    ".agents/skills/new-app",
    ".claude/skills/new-app",
}
TEMPLATE_TARGETS = ("new-app", "new-app-check", "init-app")
TEMPLATE = {"display": "BizWithAgents", "slug": "bizwithagents", "prefix": "bw", "ports": "82", "redis": (10, 11, 12)}
LOCAL_PORTS = (15432, 16379, 5673, 15673, 27018, 8799)  # hạ tầng local (compose.infra.yml) + LLM giả: mỗi app một bộ
APP_FILE = ".template.json"  # tham số đổi tên + commit template đã đồng bộ — `make template-sync` đọc (D29)


@dataclass(frozen=True)
class App:
    name: str  # tên hiển thị, vd "Task Hub"
    slug: str  # vd "taskhub"
    prefix: str  # vd "th"
    ports: str  # 2 chữ số đầu của cổng local, vd "83" → 8301–8304
    redis: tuple[int, int, int]  # dev / prod · test · stack thử

    @property
    def compact(self) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", self.name)


def validate(app: App, dest: Path, *, in_place: bool = False) -> None:
    problems = []
    if not app.compact:
        problems.append("NAME phải có chữ hoặc số")
    if not re.fullmatch(r"[a-z][a-z0-9]{2,30}", app.slug) or app.slug == TEMPLATE["slug"]:
        problems.append("SLUG: chữ thường / số, 3–31 ký tự, khác template")
    if not re.fullmatch(r"[a-z]{2,4}", app.prefix) or app.prefix == TEMPLATE["prefix"]:
        problems.append("PREFIX: 2–4 chữ thường, khác template")
    if not re.fullmatch(r"[1-9]\d", app.ports) or app.ports == TEMPLATE["ports"]:
        problems.append("PORTS: 2 chữ số (vd 83 → 8301–8304), khác template")
    if len(set(app.redis)) != 3 or not all(0 <= d <= 15 for d in app.redis) or set(app.redis) & set(TEMPLATE["redis"]):
        problems.append("REDIS_DBS: 3 số khác nhau trong 0–15, khác 10 / 11 / 12 của template (D19)")
    if not in_place and dest.exists():
        problems.append(f"DEST {dest} đã tồn tại")
    if problems:
        raise SystemExit("new-app: " + "; ".join(problems))


def rules(app: App) -> list[tuple[re.Pattern[str], str]]:
    """Bảng thay thế theo ngữ cảnh — thứ tự có ý nghĩa (riêng trước, chung sau)."""
    d0, d1, d2 = app.redis
    p = TEMPLATE["ports"]
    shift = 100 * ((int(app.ports) - int(p)) % 100)  # PORTS 83 → +100; không trùng nhau / trùng cổng app
    return [
        (re.compile(r"X-BizWithAgents-"), f"X-{app.compact}-"),  # header không được có dấu cách
        (re.compile(r"BizWithAgents"), app.name),
        (re.compile(r"BIZWITHAGENTS"), app.slug.upper()),
        (re.compile(r"bizwithagents"), app.slug),
        (re.compile(r"(?<![A-Za-z0-9])bw(?=[_\-.:`\"'/ ]|$)", re.M), app.prefix),
        (re.compile(rf"\b{p}0([1-4])\b"), rf"{app.ports}0\g<1>"),  # cổng local 8201–8204
        (re.compile(r"\b1681([1-3])\b"), rf"168{app.ports[-1]}\g<1>"),  # cổng container (tài liệu)
        (re.compile(r"(:1?6379/)10\b"), rf"\g<1>{d0}"),
        (re.compile(r'TEST_REDIS_DB = "11"'), f'TEST_REDIS_DB = "{d1}"'),
        (re.compile(r"REDIS_DB = 12\b"), f"REDIS_DB = {d2}"),
        (re.compile(r"\b([Dd]b) 10\b"), rf"\g<1> {d0}"),
        (re.compile(r"\b([Dd]b) 11\b"), rf"\g<1> {d1}"),
        (re.compile(r"\b([Dd]b) 12\b"), rf"\g<1> {d2}"),
        (re.compile(r"dev / prod 10, test 11"), f"dev / prod {d0}, test {d1}"),
        *[(re.compile(rf"\b{port}\b"), str(port + shift)) for port in LOCAL_PORTS],  # sau luật Redis db (đọc :16379/)
    ]


def rewrite(text: str, table: list[tuple[re.Pattern[str], str]]) -> str:
    for pattern, repl in table:
        text = pattern.sub(repl, text)
    return text


def copy_tree(src: Path, dest: Path) -> list[Path]:
    def ignore(directory: str, names: list[str]) -> set[str]:
        rel = Path(directory).relative_to(src)
        return {
            n for n in names if n in SKIP_DIRS or n in SKIP_FILES or (rel / n).as_posix() in TEMPLATE_ONLY
        }  # fmt: skip

    shutil.copytree(src, dest, ignore=ignore, symlinks=True)  # copy2 giữ bit thực thi
    strip_template_targets(dest)
    return [p for p in dest.rglob("*") if p.is_file() and not p.is_symlink()]


def strip_template_targets(root: Path) -> None:
    """Makefile của app không còn target tạo app (`new-app`, `new-app-check`, `init-app`)."""
    makefile = root / "Makefile"
    if not makefile.exists():
        return
    names = "|".join(re.escape(t) for t in TEMPLATE_TARGETS)
    text = re.sub(rf"(?m)^({names}):[^\n]*\n(\t[^\n]*\n)*", "", makefile.read_text(encoding="utf-8"))
    makefile.write_text(text.replace(" " + " ".join(TEMPLATE_TARGETS), ""), encoding="utf-8")


def remove_template_only(root: Path) -> list[str]:
    """Đổi tên tại chỗ: xoá công cụ chỉ của template + target Makefile tương ứng; trả đường dẫn đã xoá."""
    gone = []
    for rel in sorted(TEMPLATE_ONLY):
        path = root / rel
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
        else:
            continue
        gone.append(rel)
    strip_template_targets(root)
    return gone


def tree(root: Path) -> tuple[list[Path], list[Path]]:
    """(thư mục, file thường) dưới `root`, bỏ SKIP_DIRS / SKIP_FILES / symlink — đổi tên tại chỗ không đụng `.git`,
    `node_modules`, `.venv`, `.env`…"""
    dirs: list[Path] = []
    files: list[Path] = []
    for here, subdirs, names in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS and not (Path(here) / d).is_symlink()]
        dirs += [Path(here) / d for d in subdirs]
        files += [Path(here) / n for n in names if n not in SKIP_FILES and not (Path(here) / n).is_symlink()]
    return dirs, files


def rename(dest: Path, app: App) -> tuple[int, int]:
    """Đổi nội dung file văn bản rồi tên file / thư mục; trả (số file đổi nội dung, số đường dẫn đổi tên)."""
    table = rules(app)
    changed = 0
    dirs, files = tree(dest)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # file nhị phân (ảnh, font…)
        new = rewrite(text, table)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    moved = 0
    for path in sorted(dirs + files, key=lambda p: len(p.parts), reverse=True):  # con trước cha
        target = path.with_name(rewrite(path.name, table[:5]))
        if target != path:
            path.rename(target)
            moved += 1
    return changed, moved


def reformat(dest: Path) -> None:
    """Đổi tên làm dòng dài / ngắn đi → format lại Python (ruff cạnh interpreter đang chạy; thiếu thì bỏ qua), khoá
    lại sơ đồ archify (spec + HTML đã thay chữ cùng nhau — không cần archify) và sinh lại trang tài liệu HTML (R23)."""
    ruff = Path(sys.executable).parent / "ruff"
    backend = dest / "backend"
    if ruff.exists():
        subprocess.run([str(ruff), "format", "--quiet", ".", "../scripts"], cwd=backend, check=False)
    if (dest / "scripts/docs_site.py").exists():
        docs = [sys.executable, "../scripts/docs_site.py"]
        subprocess.run([*docs, "--relock-diagrams"], cwd=backend, check=False, capture_output=True)


def write_app_file(root: Path, app: App, template_commit: str | None) -> None:
    data = {
        "name": app.name,
        "slug": app.slug,
        "prefix": app.prefix,
        "ports": app.ports,
        "redis_dbs": list(app.redis),
        "template_commit": template_commit,
    }
    (root / APP_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def head_commit(root: Path) -> str | None:
    """Commit template đang đứng (gốc để `make template-sync` tính phần chênh); không phải repo git → None."""
    res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return res.stdout.strip() if res.returncode == 0 and (root / ".git").exists() else None


def _git(root: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} lỗi: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout


def git_init(dest: Path, app: App) -> None:
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", f"chore: tạo {app.name} từ template BizWithAgents")


def in_place_problems(root: Path) -> list[str]:
    """Chặn đổi tên nhầm: thư mục còn tên template (bản template đang phát triển), cây git chưa sạch, đã đổi tên rồi."""
    problems = []
    if root.name.lower() == TEMPLATE["slug"]:
        problems.append(
            f"thư mục {root.name} là bản template — clone sang thư mục mang tên app: git clone <repo> ../<slug>, "
            "hoặc dùng `make new-app DEST=../<slug>`"
        )
    makefile = root / "Makefile"
    if not makefile.exists() or TEMPLATE["slug"] not in makefile.read_text(encoding="utf-8"):
        problems.append("repo không còn tên template — đã đổi tên rồi?")
    if not (root / ".git").exists():
        problems.append("không phải repo git — clone template bằng git trước")
    elif _git(root, "status", "--porcelain").strip():
        problems.append("cây git còn thay đổi chưa commit — commit / stash trước (đổi tên tạo một commit riêng)")
    return problems


def git_adopt(root: Path, app: App) -> list[str]:
    """Sau khi đổi tên tại chỗ: `origin` (repo template) → `template` để còn kéo bản sửa về; commit đổi tên."""
    notes = []
    remotes = _git(root, "remote").split()
    if "origin" in remotes and "template" not in remotes:
        _git(root, "remote", "rename", "origin", "template")
        notes.append("remote origin → template (bản sửa của template: git fetch template && git merge template/main)")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", f"chore: tạo {app.name} từ template BizWithAgents")
    return notes


CHECKLIST = """Tiếp theo:
  1. {cd}`make setup SUPERADMIN=<email> VERIFY=1` — cài phụ thuộc, .env, khoá, hạ tầng local bằng Docker, migrate,
     stack thử + smoke. Thêm `MODE=shared` nếu dùng hạ tầng chung (D19): chủ dự án tạo DB `{slug}` / `{slug}_test`
     / `{slug}_e2e`, vhost cùng tên, Mongo DB `{slug}`, Redis db {d0} · {d1} · {d2}.
  2. Repo GitHub mới → `git remote add origin <url>` → `git push -u origin main`; app Coolify + domain + `PUBLIC_URL`
     (deploy/CLAUDE.md).
  3. Sửa mục Project Context trong CLAUDE.md + README.md cho đúng sản phẩm; thêm tính năng bằng skill `new-module`
     (Claude Code / Codex / Gemini: "thêm module …").
  4. Bản sửa của template về sau: `make template-sync` (cần remote `template` — {remote})."""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tạo app mới từ template BizWithAgents")
    p.add_argument("--name", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--ports", required=True)
    p.add_argument("--redis-dbs", required=True, help="3 số: dev / prod, test, stack thử — vd 4,5,6 (Redis có db 0–15)")
    p.add_argument("--dest", type=Path, help="chép sang thư mục mới (bỏ qua khi --in-place)")
    p.add_argument("--in-place", action="store_true", help="đổi tên ngay trong bản clone ở --src (D27)")
    p.add_argument("--src", type=Path, default=ROOT)
    p.add_argument("--no-git", action="store_true")
    a = p.parse_args(argv)
    try:
        dbs = tuple(int(x) for x in a.redis_dbs.split(","))
    except ValueError as exc:
        raise SystemExit("REDIS_DBS phải là 3 số cách nhau dấu phẩy") from exc
    if len(dbs) != 3:
        raise SystemExit("REDIS_DBS phải đúng 3 số")
    app = App(a.name.strip(), a.slug, a.prefix, a.ports, dbs)  # type: ignore[arg-type]
    if a.in_place:
        return _in_place(app, a.src.resolve(), git=not a.no_git)
    if a.dest is None:
        raise SystemExit("thiếu --dest (hoặc dùng --in-place trong bản clone)")
    dest = a.dest.resolve()
    validate(app, dest)
    files = copy_tree(a.src.resolve(), dest)
    changed, moved = rename(dest, app)
    reformat(dest)
    write_app_file(dest, app, head_commit(a.src.resolve()))
    if not a.no_git:
        git_init(dest, app)
    print(f"✓ {app.name} ({app.slug}, tiền tố {app.prefix}) ở {dest}: {len(files)} file, đổi {changed}, tên {moved}")
    d0, d1, d2 = app.redis
    remote = "`git remote add template <url repo template>`"
    print(CHECKLIST.format(cd=f"`cd {dest}` → ", slug=app.slug, d0=d0, d1=d1, d2=d2, remote=remote))
    return 0


def _in_place(app: App, root: Path, *, git: bool) -> int:
    validate(app, root, in_place=True)
    problems = in_place_problems(root) if git else []
    if problems:
        raise SystemExit("init-app: " + "; ".join(problems))
    base = head_commit(root) if git else None
    gone = remove_template_only(root)
    changed, moved = rename(root, app)
    reformat(root)
    write_app_file(root, app, base)
    notes = git_adopt(root, app) if git else []
    print(
        f"✓ {app.name} ({app.slug}, tiền tố {app.prefix}) tại {root}: đổi {changed} file, tên {moved}, xoá {len(gone)}"
    )
    for note in notes:
        print(f"  {note}")
    if (root / ".env").exists():
        print("  ! .env có sẵn không đổi — kiểm lại tên DB / vhost / SERVICE_PATH theo tên mới")
    d0, d1, d2 = app.redis
    print(CHECKLIST.format(cd="", slug=app.slug, d0=d0, d1=d1, d2=d2, remote="init-app đã đặt sẵn"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
