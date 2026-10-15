"""Mã lỗi __title_vi__ — dải module __code__–__code_max__."""

from __future__ import annotations

from app.core.errors import register_errors

__MOD___ERRORS: dict[int, str] = {
    __code1__: "__title_en__ item not found",
}
register_errors(__MOD___ERRORS, owner="__mod__")
