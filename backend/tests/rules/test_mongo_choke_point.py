"""R12: nghiệp vụ không chạm Mongo — chỉ `app/core/` (kết nối) và `app/observability/` (sink + store) được import
pymongo / beanie hay đọc thuộc tính `.mongo`."""

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
ALLOWED = {"core", "observability"}
MONGO_LIBS = {"pymongo", "beanie", "motor"}


def _imported(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]
    return []


def test_business_code_never_touches_mongo():
    bad = []
    for path in sorted(APP.rglob("*.py")):
        parts = path.relative_to(APP).parts
        if len(parts) == 1 or parts[0] in ALLOWED:  # main.py / cli.py chỉ chuyển kết nối cho init_observability
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            rel = f"{path.relative_to(APP).as_posix()}:{getattr(node, 'lineno', 0)}"
            bad += [f"{rel} import {name}" for name in _imported(node) if name.split(".")[0] in MONGO_LIBS]
            if isinstance(node, ast.Attribute) and node.attr == "mongo":
                bad.append(f"{rel} .mongo")
    assert not bad, "chạm Mongo ngoài choke-point (R12):\n  " + "\n  ".join(bad)
