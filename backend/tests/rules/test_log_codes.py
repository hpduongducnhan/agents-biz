"""Mã `loc`: dạng `<tiền tố><4 số>`, tiền tố khai ở `LOG_PREFIXES`, không trùng trong backend/app;
log warning / error phải có loc."""

import ast
import pathlib
import re
from collections import Counter

from app.core.logging import ALL_LOG_PREFIXES

BACKEND = pathlib.Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
LOC_RE = re.compile(r"^([a-z]{2,6})\d{4}$")
MUST_HAVE_LOC = {"warning", "error", "exception", "critical"}


def _trees():
    for path in sorted(APP.rglob("*.py")):
        yield path.relative_to(BACKEND).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def _loc_literals():
    for rel, tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=True):
                is_loc = isinstance(key, ast.Constant) and key.value == "loc"
                if is_loc and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    yield rel, node.lineno, value.value


def test_scanner_sees_known_codes():
    assert {"boot0001", "http0500", "hout0001"} <= {code for _, _, code in _loc_literals()}


def test_loc_codes_well_formed_with_known_prefix():
    bad = []
    for rel, line, code in _loc_literals():
        m = LOC_RE.match(code)
        if m is None or m.group(1) not in ALL_LOG_PREFIXES:
            bad.append(f"{rel}:{line} {code}")
    assert not bad, "mã loc sai dạng / tiền tố lạ:\n  " + "\n  ".join(bad)


def test_loc_codes_unique():
    counts = Counter(code for _, _, code in _loc_literals())
    dupes = sorted(code for code, n in counts.items() if n > 1)
    assert not dupes, f"mã loc bị dùng nhiều chỗ: {dupes}"


def _has_loc(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "extra" and isinstance(kw.value, ast.Dict):
            return any(isinstance(k, ast.Constant) and k.value == "loc" for k in kw.value.keys)
    return False


def test_warning_and_error_logs_carry_loc():
    missing = []
    for rel, tree in _trees():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in MUST_HAVE_LOC
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
                and not _has_loc(node)
            ):
                missing.append(f"{rel}:{node.lineno}")
    assert not missing, "warning / error thiếu extra loc:\n  " + "\n  ".join(missing)
