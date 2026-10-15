"""`make new-module NAME=notes TITLE="Ghi chú" [TITLE_EN="Notes"]` — sinh module CRUD theo khuôn Tasks (D15, D25):
backend (model theo tenant, 5 op, quyền, mã lỗi, trợ lý), migration, test, câu ý định, frontend (manifest, trang, form,
test) + chèn một dòng đăng ký ở 6 chỗ lõi. Chạy lại với module đã có → dừng, không ghi đè.

    python scripts/scaffold/new_module.py notes --title "Ghi chú" [--title-en "Notes"] [--root <repo>]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = Path(__file__).resolve().parent / "templates" / "module"
NAME_RE = re.compile(r"[a-z][a-z0-9_]{1,30}")
RESERVED = {"core", "models", "devtools", "system", "auth", "tenants", "mail", "observability", "notifications"}
RESERVED |= {"credentials", "agent", "tasks", "modules", "types", "registry", "access", "test", "tests"}
FIRST_MODULE_CODE = 10000  # dải module `1NNxx` (template-v1 §3.4)


@dataclass(frozen=True)
class Spec:
    name: str
    title_vi: str
    title_en: str
    code: int
    loc: str
    rev: str
    down_rev: str

    @property
    def tokens(self) -> dict[str, str]:
        """Thay token dài trước để không cắt nhầm (`__title_vi_lower__` trước `__title_vi__`)."""
        pascal = "".join(p.capitalize() for p in self.name.split("_"))
        return {
            "__title_vi_lower__": self.title_vi.lower(),
            "__title_en_lower__": self.title_en.lower(),
            "__title_vi__": self.title_vi,
            "__title_en__": self.title_en,
            "__code_max__": str(self.code + 99),
            "__code1__": str(self.code + 1),
            "__code__": str(self.code),
            "__down_rev__": self.down_rev,
            "__rev__": self.rev,
            "__route__": self.name.replace("_", "-"),
            "__loc__": self.loc,
            "__MOD__": self.name.upper(),
            "__Mod__": pascal,
            "__mod__": self.name,
        }


def render(text: str, tokens: dict[str, str]) -> str:
    for token, value in tokens.items():
        text = text.replace(token, value)
    return text


def next_code(errors_py: str) -> int:
    used = [int(m) for m in re.findall(r"\((1\d{4}), 1\d{4}\)", errors_py)]
    return max(used) + 100 if used else FIRST_MODULE_CODE


def loc_prefix(name: str, logging_py: str) -> str:
    taken = set(re.findall(r'"([a-z]{2,6})"', logging_py))
    letters = re.sub(r"[^a-z]", "", name)
    for size in range(3, 7):
        cand = letters[:size]
        if len(cand) == size and cand not in taken:
            return cand
    raise SystemExit(f"không tìm được tiền tố `loc` cho '{name}' — tự thêm vào LOG_PREFIXES")


def head(versions: Path) -> tuple[str, int]:
    revs, downs = {}, set()
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = re.search(r'^revision = "([^"]+)"', text, re.M)
        down = re.search(r'^down_revision = "([^"]+)"', text, re.M)
        if rev:
            revs[rev.group(1)] = int(rev.group(1).split("_", 1)[0])
        if down:
            downs.add(down.group(1))
    (tip,) = [r for r in revs if r not in downs]
    return tip, max(revs.values())


def insert_before(text: str, anchor: str, closing: str, line: str) -> str:
    """Chèn `line` ngay trước `closing` đầu tiên sau `anchor` (đã có → giữ nguyên)."""
    if line.strip() in text:
        return text
    start = text.index(anchor)
    end = text.index(closing, start)
    return text[:end] + line + text[end:]


def register(root: Path, spec: Spec) -> list[str]:
    """Một dòng ở mỗi chỗ lõi đọc danh sách module; trả các file đã sửa."""
    n, pascal = spec.name, spec.tokens["__Mod__"]
    edits = {
        "backend/app/domains.py": lambda t: insert_before(t, "DOMAINS = (", "\n)", f'\n    "{n}",'),
        "backend/app/core/errors.py": lambda t: insert_before(
            t, "ERROR_RANGES", "\n}", f'\n    "{n}": ({spec.code}, {spec.code + 99}),'
        ),
        "backend/app/core/logging.py": lambda t: insert_before(
            t, "LOG_PREFIXES", "\n}", f'\n    "{n}": frozenset({{"{spec.loc}"}}),'
        ),
        "backend/app/models/__init__.py": lambda t: (
            t
            if f"app.{n}.models" in t
            else t.rstrip("\n") + f"\nfrom app.{n}.models import {pascal}Item  # noqa: F401\n"
        ),
        "frontend/src/modules/registry.ts": lambda t: _registry_ts(t, n),
        "frontend/src/lib/api/endpoints.ts": lambda t: insert_before(
            t,
            "export const ENDPOINTS = {",
            "\n} as const",
            "".join(f'\n  "{n}.{op}": "{m}",' for op, m in OPS),
        ),
    }
    changed = []
    for rel, edit in edits.items():
        path = root / rel
        before = path.read_text(encoding="utf-8")
        after = edit(before)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed.append(rel)
    return changed


OPS = (("list", "GET"), ("get", "GET"), ("create", "POST"), ("update", "POST"), ("delete", "POST"))


def _registry_ts(text: str, name: str) -> str:
    if f'from "./{name}"' in text:
        return text
    imports = [m.end() for m in re.finditer(r'^import \{ \w+ \} from "\./\w+";$', text, re.M)]
    text = text[: imports[-1]] + f'\nimport {{ {name}Module }} from "./{name}";' + text[imports[-1] :]
    return re.sub(r"(export const MODULES: ModuleManifest\[\] = \[[^\]]*)\]", rf"\1, {name}Module]", text)


def generate(root: Path, spec: Spec) -> list[Path]:
    if (root / "backend" / "app" / spec.name).exists():
        raise SystemExit(f"module '{spec.name}' đã có ở backend/app/{spec.name} — không ghi đè")
    written = []
    for src in sorted(TEMPLATES.rglob("*")):
        if not src.is_file():
            continue
        dest = root / render(str(src.relative_to(TEMPLATES)), spec.tokens)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render(src.read_text(encoding="utf-8"), spec.tokens), encoding="utf-8")
        written.append(dest)
    return written


def tidy(root: Path, written: list[Path]) -> None:
    """Format + sửa import của file Python sinh ra (ruff cạnh interpreter đang chạy); thiếu ruff thì bỏ qua."""
    ruff = Path(sys.executable).parent / "ruff"
    files = [str(p) for p in written if p.suffix == ".py"]
    if not ruff.exists() or not files:
        return
    backend = root / "backend"
    subprocess.run([str(ruff), "format", "--quiet", *files], cwd=backend, check=False)
    subprocess.run([str(ruff), "check", "--fix", "--quiet", *files], cwd=backend, check=False)
    subprocess.run([str(ruff), "format", "--quiet", *files], cwd=backend, check=False)  # sau khi sắp import


def plan(root: Path, name: str, title_vi: str, title_en: str) -> Spec:
    if not NAME_RE.fullmatch(name) or name in RESERVED:
        raise SystemExit(f"tên module '{name}' phải chữ thường / số / gạch dưới, 2–31 ký tự, không trùng miền lõi")
    tip, top = head(root / "backend" / "migrations" / "versions")
    return Spec(
        name=name,
        title_vi=title_vi,
        title_en=title_en,
        code=next_code((root / "backend/app/core/errors.py").read_text(encoding="utf-8")),
        loc=loc_prefix(name, (root / "backend/app/core/logging.py").read_text(encoding="utf-8")),
        rev=f"{top + 1:04d}_{name}",
        down_rev=tip,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sinh module CRUD theo khuôn Tasks")
    p.add_argument("name")
    p.add_argument("--title", required=True, help="tên hiển thị tiếng Việt, vd 'Ghi chú'")
    p.add_argument("--title-en", default=None, help="tên hiển thị tiếng Anh (mặc định = tên module)")
    p.add_argument("--root", type=Path, default=ROOT)
    a = p.parse_args(argv)
    spec = plan(a.root, a.name, a.title.strip(), (a.title_en or a.name.replace("_", " ").title()).strip())
    written = generate(a.root, spec)
    changed = register(a.root, spec)
    tidy(a.root, [*written, a.root / "backend/app/models/__init__.py"])
    print(f"✓ module {spec.name}: {len(written)} file, mã lỗi {spec.code}–{spec.code + 99}, loc {spec.loc}, {spec.rev}")
    for rel in changed:
        print(f"  sửa {rel}")
    print(
        "Tiếp: `make openapi fe-gen-api` → `make be-lint fe-typecheck` → sửa field / luật nghiệp vụ ở backend/app/"
        f"{spec.name}/ → viết prompt + bổ sung câu ý định (≥ 30 mỗi ngôn ngữ) → `make ci`."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
