"""`make template-sync [REF=template/main]` — kéo bản sửa của template về app đã đổi tên (D29).

Makefile của app lấy bản mới nhất của file này + `new_app.py` từ remote `template` (`git archive` → `debug/`) rồi chạy:
dựng cây template ở commit đã đồng bộ (`.template.json`) và ở REF, đổi tên cả hai bằng đúng luật của `init-app`, rồi
`git cherry-pick` phần chênh lên app. Xung đột chỉ còn ở chỗ app và template cùng sửa; file mới của template vào app
đã mang tên app. Cuối cùng kiểm không còn tên template ở file vừa đổi.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from new_app import APP_FILE, TEMPLATE, App, reformat, remove_template_only, rename

LEFTOVER = re.compile(
    "|".join([TEMPLATE["display"], TEMPLATE["slug"], TEMPLATE["slug"].upper()])
    + rf"|(?<![A-Za-z0-9]){TEMPLATE['prefix']}(?=[_\-.:`\"'/ ]|$)",
    re.M,
)
GENERATED = (
    "make docs · make openapi fe-gen-api (file sinh: .claude/**/*.html, search-index.js, openapi.json, schema.d.ts)"
)


def git(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    res = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False, env=env)
    if check and res.returncode != 0:
        raise SystemExit(f"template-sync: git {' '.join(args)} lỗi: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout.strip()


def load_app(root: Path) -> tuple[App, str | None]:
    path = root / APP_FILE
    if not path.exists():
        raise SystemExit(f"template-sync: thiếu {APP_FILE} — chỉ chạy trong app tạo bằng `make init-app` / `new-app`")
    data = json.loads(path.read_text(encoding="utf-8"))
    app = App(data["name"], data["slug"], data["prefix"], data["ports"], tuple(data["redis_dbs"]))  # type: ignore[arg-type]
    return app, data.get("template_commit")


def save_commit(root: Path, commit: str) -> None:
    path = root / APP_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    data["template_commit"] = commit
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def problems(root: Path, base: str | None) -> list[str]:
    found = []
    if git(root, "status", "--porcelain"):
        found.append("cây git còn thay đổi chưa commit — commit / stash trước")
    if (root / ".git/CHERRY_PICK_HEAD").exists():
        found.append("đang dở một lần đồng bộ — sửa xung đột rồi `git cherry-pick --continue` (hoặc `--abort`)")
    if not base:
        found.append(f"{APP_FILE} chưa có template_commit — ghi sha commit template mà app được tạo ra từ đó")
    elif not git(root, "cat-file", "-t", f"{base}^{{commit}}", check=False):
        found.append(f"chưa có commit template {base[:12]} — `git fetch template` (remote phải trỏ repo template)")
    return found


def renamed_tree(root: Path, commit: str, app: App, work: Path) -> str:
    """Cây template ở `commit` sau khi đổi tên như `init-app` (bỏ công cụ chỉ của template, đổi tên, format, khoá
    sơ đồ + sinh lại tài liệu); ghi vào kho git của app, trả sha cây."""
    tree = work / commit[:12]
    tree.mkdir(parents=True)
    archive = work / f"{commit[:12]}.tar"
    git(root, "archive", "-o", str(archive), commit)
    subprocess.run(["tar", "-xf", str(archive), "-C", str(tree)], check=True)
    remove_template_only(tree)
    rename(tree, app)
    reformat(tree)
    env = {
        **os.environ,
        "GIT_DIR": str(root / ".git"),
        "GIT_WORK_TREE": str(tree),
        "GIT_INDEX_FILE": str(work / f"{commit[:12]}.index"),
    }
    git(tree, "add", "-A", env=env)
    return git(tree, "write-tree", env=env)


def leftovers(root: Path, ref: str) -> list[str]:
    """File vừa đổi trong commit `ref` còn tên template (luật đổi tên chưa phủ chỗ mới)."""
    names = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "--diff-filter=AM", ref).splitlines()
    hits = []
    for name in names:
        path = root / name
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if LEFTOVER.search(text) or LEFTOVER.search(name):
            hits.append(name)
    return hits


def sync(root: Path, ref: str, work: Path) -> int:
    app, base = load_app(root)
    target = git(root, "rev-parse", f"{ref}^{{commit}}")
    found = problems(root, base)
    if found:
        raise SystemExit("template-sync: " + "; ".join(found))
    assert base is not None
    if target == base:
        print(f"✓ đã khớp template {target[:12]} — không có gì để kéo")
        return 0
    shutil.rmtree(work, ignore_errors=True)
    old_tree = renamed_tree(root, base, app, work)
    new_tree = renamed_tree(root, target, app, work)
    message = f"chore: đồng bộ template {target[:12]} (từ {base[:12]})"
    if old_tree == new_tree:
        save_commit(root, target)
        git(root, "add", APP_FILE)
        git(root, "commit", "-q", "-m", f"{message} — không đổi gì ở app")
        print(f"✓ template {base[:12]} → {target[:12]}: không có thay đổi nào cho app (chỉ công cụ của template)")
        shutil.rmtree(work, ignore_errors=True)
        return 0
    old = git(root, "commit-tree", old_tree, "-m", f"template {base[:12]} (đã đổi tên)")
    new = git(root, "commit-tree", new_tree, "-p", old, "-m", message)
    picked = subprocess.run(
        ["git", "cherry-pick", "--keep-redundant-commits", new], cwd=root, capture_output=True, text=True, check=False
    )
    save_commit(root, target)
    git(root, "add", APP_FILE)
    if picked.returncode != 0:
        conflicts = git(root, "diff", "--name-only", "--diff-filter=U").splitlines()
        print(f"✗ xung đột ở {len(conflicts)} file (app và template cùng sửa):")
        for name in conflicts:
            print(f"    {name}")
        print(
            "  Sửa từng file (giữ tên app); file sinh tự động lấy bản nào cũng được rồi sinh lại: "
            f"{GENERATED}.\n  Xong: `git add <file>` → `git cherry-pick --continue` → `make ci`. "
            "Bỏ lần đồng bộ: `git cherry-pick --abort && git checkout HEAD -- .template.json`."
        )
        return 1
    git(root, "commit", "-q", "--amend", "--no-edit")
    shutil.rmtree(work, ignore_errors=True)
    changed = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
    head = git(root, "rev-parse", "--short", "HEAD")
    print(f"✓ đồng bộ template {base[:12]} → {target[:12]}: {len(changed)} file, commit {head}")
    hits = leftovers(root, "HEAD")
    if hits:
        print("✗ còn tên template ở các file dưới (luật đổi tên chưa phủ) — sửa tay rồi commit:")
        for name in hits:
            print(f"    {name}")
        return 1
    print(f"  Tiếp theo: {GENERATED} → `make ci` → commit nếu có file sinh lại.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Kéo bản sửa của template về app đã đổi tên (D29)")
    p.add_argument("--app", type=Path, default=Path.cwd(), help="thư mục gốc của app")
    p.add_argument("--ref", default="template/main", help="commit / nhánh / tag template cần kéo về")
    a = p.parse_args(argv)
    root = a.app.resolve()
    return sync(root, a.ref, root / "debug" / "template-sync" / "work")


if __name__ == "__main__":
    sys.exit(main())
