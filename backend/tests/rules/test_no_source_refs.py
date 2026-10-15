"""Code không nhắc tài liệu của dự án nguồn (R3): `v1-design §…`, `sp*-index §…` — comment trỏ tài
liệu của template (`.claude/`) hoặc quyết định `D<n>` của chính app."""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]
SCAN = (
    "backend/app",
    "backend/tests",
    "frontend/src",
    "frontend/test",
    "realtime/src",
    "realtime/test",
    "realtime/scripts",
)
SKIP = {
    "frontend/src/lib/api/openapi.json",
    "frontend/src/lib/api/schema.d.ts",
    "backend/tests/rules/test_no_source_refs.py",
}
SUFFIXES = {".py", ".ts", ".tsx", ".lua", ".mjs"}
PATTERNS = {
    "v1-design": re.compile(r"v1-design"),
    "sp-index": re.compile(r"\bsp\d+[a-z]?\d*-index\b"),
}


def offenders() -> list[str]:
    found = []
    for root in SCAN:
        for path in sorted((REPO / root).rglob("*")):
            rel = path.relative_to(REPO).as_posix()
            if path.suffix not in SUFFIXES or rel in SKIP or "node_modules" in path.parts:
                continue
            for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                hits = [name for name, pat in PATTERNS.items() if pat.search(line)]
                if hits:
                    found.append(f"{rel}:{no} [{', '.join(hits)}] {line.strip()[:90]}")
    return found


def test_code_has_no_source_project_references():
    bad = offenders()
    assert not bad, "tham chiếu tài liệu dự án nguồn trong code (R3):\n  " + "\n  ".join(bad[:40])
