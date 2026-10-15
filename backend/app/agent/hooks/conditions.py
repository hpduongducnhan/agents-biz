"""Điều kiện + mẫu chữ của hook (có so sánh số): đường dẫn chấm
(`args.amount`, `run.tools.0`), mệnh đề `{path, op, value}` nối AND, `{{path}}` trong chữ."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

TOKEN_RE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
COMPARE = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
}


def lookup(data: dict[str, Any], path: str) -> tuple[bool, Any]:
    """(có không, giá trị) — số trong đường dẫn chọn phần tử danh sách; `a[0]` cũng được."""
    node: Any = data
    for part in path.replace("[", ".").replace("]", "").split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False, None
    return True, node


def _same(a: Any, b: Any) -> bool:
    return a == b or (a is not None and b is not None and str(a) == str(b))  # "5" khớp 5 (form gõ chữ)


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def holds(cond: dict[str, Any], data: dict[str, Any]) -> bool:
    found, value = lookup(data, cond["path"])
    op, want = cond["op"], cond.get("value")
    if op == "exists":
        return (found and value is not None) == (want is not False)
    if op == "eq":
        return found and _same(value, want)
    if op == "ne":
        return not (found and _same(value, want))
    if op == "in":
        return found and any(_same(value, w) for w in (want if isinstance(want, list) else [want]))
    if op == "contains":
        if not found:
            return False
        return any(_same(x, want) for x in value) if isinstance(value, list) else str(want) in str(value or "")
    a, b = _number(value), _number(want)
    return found and a is not None and b is not None and COMPARE[op](a, b)


def matches(conditions: list[dict[str, Any]], data: dict[str, Any]) -> bool:
    return all(holds(c, data) for c in conditions)


def render(template: str, data: dict[str, Any]) -> str:
    def text(m: re.Match) -> str:
        value = lookup(data, m.group(1))[1]
        if value is None:
            return ""
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)

    return TOKEN_RE.sub(text, template)
