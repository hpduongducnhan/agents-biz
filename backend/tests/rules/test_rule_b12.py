"""Rule B12 — bắt exception rộng mà không log và không ném lại là hỏng âm thầm."""

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[3]
SCAN = [REPO / "backend" / "app"]
BROAD = {"Exception", "BaseException"}
LOG_CALLS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
# Miễn trừ có chủ ý — mỗi mục PHẢI có comment nhắc "Rule B12" trong mã nguồn.
EXEMPT = {("backend/app/core/logging.py", "JSON formatter fallback — log ở đây sẽ đệ quy")}
EXEMPT_FILES = {path for path, _ in EXEMPT}


def _caught(handler: ast.ExceptHandler) -> set[str]:
    if handler.type is None:
        return {"<bare>"}
    return {n.id for n in ast.walk(handler.type) if isinstance(n, ast.Name)}


def _logs_or_reraises(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_CALLS:
            return True
    return False


def _offenders() -> list[str]:
    found = []
    for root in SCAN:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            for h in (n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ExceptHandler)):
                if _logs_or_reraises(h) or rel in EXEMPT_FILES:
                    continue
                if _caught(h) & (BROAD | {"<bare>"}):
                    found.append(f"{rel}:{h.lineno}  {lines[h.lineno - 1].strip()[:80]}")
    return found


def test_no_broad_exception_swallowed_without_logging():
    offenders = _offenders()
    assert not offenders, "Rule B12: bắt Exception rộng mà không log / không raise:\n  " + "\n  ".join(offenders)


def test_exempt_files_exist_and_explain_themselves():
    for rel, _reason in EXEMPT:
        path = REPO / rel
        assert path.exists(), f"{rel} không còn — dọn khỏi danh sách miễn trừ"
        assert "Rule B12" in path.read_text(encoding="utf-8"), f"{rel} được miễn trừ nhưng không có comment Rule B12"
