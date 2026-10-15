"""Điều kiện hook: đường dẫn chấm, các phép so sánh, mẫu `{{path}}`."""

from decimal import Decimal

import pytest

from app.agent.hooks.conditions import holds, lookup, matches, render
from app.agent.hooks.schemas import MAX_CONDITIONS, Condition

DATA = {
    "args": {"amount": 2_500_000, "note": "tiền nhà tháng 10", "tags": ["a", "b"], "cat": "Nhà", "ok": True, "zero": 0},
    "tool": {"name": "wallet_record_expense", "toolset": "ledger"},
    "run": {"tools": ["x", "y"], "cost": Decimal("0.5")},
    "user": {"name": "An", "roles": ["user", "admin"]},
    "items": [{"id": 1}, {"id": 2}],
}


def cond(path, op, value=None):
    return {"path": path, "op": op, "value": value}


@pytest.mark.parametrize(
    ("path", "found", "value"),
    [
        ("args.amount", True, 2_500_000),
        ("run.tools.1", True, "y"),
        ("run.tools[0]", True, "x"),
        ("items[1].id", True, 2),
        ("items.5", False, None),
        ("args.nope", False, None),
        ("nope.deep", False, None),
        ("args.amount.deeper", False, None),
    ],
)
def test_lookup_paths(path, found, value):
    assert lookup(DATA, path) == (found, value)


@pytest.mark.parametrize(
    ("c", "want"),
    [
        (cond("args.amount", "gt", 1_000_000), True),
        (cond("args.amount", "gt", 2_500_000), False),
        (cond("args.amount", "gte", 2_500_000), True),
        (cond("args.amount", "lt", "3000000"), True),  # số dạng chữ
        (cond("args.amount", "lte", 2_499_999), False),
        (cond("args.note", "gt", 1), False),  # không phải số → không so sánh được
        (cond("args.ok", "gt", 0), False),  # bool không tính là số
        (cond("args.nope", "gt", 0), False),
        (cond("args.cat", "eq", "Nhà"), True),
        (cond("args.amount", "eq", "2500000"), True),  # "5" khớp 5
        (cond("args.cat", "eq", "khác"), False),
        (cond("args.nope", "eq", None), False),
        (cond("args.cat", "ne", "Nhà"), False),
        (cond("args.cat", "ne", "khác"), True),
        (cond("args.nope", "ne", "x"), True),
        (cond("tool.name", "in", ["wallet_record_expense", "wallet_record_income"]), True),
        (cond("tool.name", "in", ["x"]), False),
        (cond("tool.name", "in", "wallet_record_expense"), True),  # giá trị đơn coi như danh sách một phần tử
        (cond("args.note", "contains", "tiền nhà"), True),
        (cond("args.note", "contains", "điện"), False),
        (cond("args.tags", "contains", "b"), True),
        (cond("args.tags", "contains", "z"), False),
        (cond("args.nope", "contains", "z"), False),
        (cond("args.cat", "exists"), True),
        (cond("args.cat", "exists", True), True),
        (cond("args.nope", "exists"), False),
        (cond("args.nope", "exists", False), True),
        (cond("args.cat", "exists", False), False),
        (cond("args.zero", "exists"), True),
        (cond("run.cost", "lt", 1), True),
    ],
)
def test_conditions_ops_and_paths(c, want):
    assert holds(c, DATA) is want


def test_matches_ands_all_conditions_and_empty_matches():
    assert matches([], DATA)
    assert matches([cond("args.amount", "gt", 1), cond("args.cat", "eq", "Nhà")], DATA)
    assert not matches([cond("args.amount", "gt", 1), cond("args.cat", "eq", "x")], DATA)


def test_render_templates():
    assert render("Chào {{user.name}}!", DATA) == "Chào An!"
    assert render("{{ args.amount }} đ", DATA) == "2500000 đ"
    assert render("tags={{args.tags}}", DATA) == 'tags=["a", "b"]'
    assert render("thiếu={{args.nope}}.", DATA) == "thiếu=." and render("không có mẫu", DATA) == "không có mẫu"


def test_condition_schema_rejects_bad_paths_ops_and_extra_fields():
    assert Condition.model_validate(cond("args.amount", "gt", 5)).path == "args.amount"
    assert Condition.model_validate(cond("run.tools[0]", "eq", "x"))
    for bad in (
        cond("Args.X", "eq"),
        cond("", "eq"),
        cond("args.x", "regex"),
        {**cond("a", "eq"), "extra": 1},
        cond("a b", "eq"),
    ):
        with pytest.raises(ValueError):  # noqa: PT011 — ValidationError là ValueError
            Condition.model_validate(bad)
    assert MAX_CONDITIONS == 10
