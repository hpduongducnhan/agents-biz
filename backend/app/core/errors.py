"""Mã lỗi + AppException. Mỗi miền một dải; đăng ký ngoài dải là lỗi cấu hình."""

from __future__ import annotations

CORE_ERRORS: dict[int, str] = {
    1000: "Internal server error",
    1001: "Not found",
    1002: "Validation error",
    1003: "Bad request",
    1004: "Not authenticated",
    1005: "Permission denied",
    1006: "Conflict",
    1007: "Too many requests",
    1008: "Service not ready",
    1009: "Request expired before it was processed",
}
ERROR_RANGES: dict[str, tuple[int, int]] = {
    "core": (1000, 1999),
    "auth": (2000, 2999),
    "agent": (6000, 6999),
    "observability": (7000, 7999),
    "notifications": (7000, 7999),
    "mail": (8000, 8999),
    "tasks": (10000, 10099),  # module dùng 5 chữ số `1NNxx` (template-v1 §3.4)
}
_REGISTRY: dict[int, tuple[str, str]] = {code: (msg, "core") for code, msg in CORE_ERRORS.items()}


def register_errors(codes: dict[int, str], *, owner: str) -> None:
    """Đăng ký mã lỗi của một miền. Owner lạ, mã ngoài dải của owner, trùng mã miền khác = lỗi cấu hình → dừng."""
    if owner not in ERROR_RANGES:
        raise ValueError(f"owner mã lỗi '{owner}' không có trong ERROR_RANGES")
    low, high = ERROR_RANGES[owner]
    outside = sorted(c for c in codes if not low <= c <= high)
    if outside:
        raise ValueError(f"Mã lỗi ngoài dải {low}–{high} của {owner}: {outside}")
    clash = {c: _REGISTRY[c][1] for c in codes if c in _REGISTRY and _REGISTRY[c][1] != owner}
    if clash:
        raise ValueError(f"Mã lỗi trùng khi đăng ký cho {owner}: {clash}")
    for code, message in codes.items():
        _REGISTRY[code] = (message, owner)


def registered_errors() -> dict[int, tuple[str, str]]:
    """Bản sao registry `{mã: (thông điệp, owner)}` — test luật kiểm dải."""
    return dict(_REGISTRY)


def error_message(code: int) -> str:
    entry = _REGISTRY.get(code)
    return entry[0] if entry else f"Error {code}"


class AppException(Exception):
    """Lỗi nghiệp vụ mang HTTP status + mã ổn định; handler render thành ApiResponse."""

    def __init__(self, code: int, status_code: int = 400, detail: str | None = None, data: object = None) -> None:
        self.code = code
        self.status_code = status_code
        self.message = detail or error_message(code)
        self.data = data
        super().__init__(self.message)
