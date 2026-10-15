"""Rule B14 — dữ liệu khách hàng tách theo tenant (D10–D11): bảng mới kế thừa `TenantScoped`, trừ bảng nền tảng liệt kê
dưới đây kèm lý do; SQL thô (`text()`) và bảng Core (`Model.__table__`) không chạm bảng `TenantScoped` — bộ lọc tự động
chỉ chạy trên câu ORM."""

import ast
import pathlib
import re

from sqlmodel import SQLModel

import app.models  # noqa: F401 — nạp mọi bảng vào metadata
from app.core.tenancy import scoped_models

REPO = pathlib.Path(__file__).resolve().parents[3]
SCAN = REPO / "backend" / "app"
GUARD = "công cụ superadmin: chặn / hạn mức chat từng user (D22)"
AGENT_CONFIG = "cấu hình agent dùng chung mọi tenant (D3)"
# Bảng toàn nền tảng — không có tenant_id. Thêm vào đây phải có lý do; bảng của module nghiệp vụ thì KHÔNG.
PLATFORM = {
    "tenants": "chính là danh sách tenant",
    "permissions": "catalog quyền sinh từ code",
    "roles": "role dùng chung mọi tenant (D12)",
    "role_permissions": "quyền của role dùng chung",
    "user_roles": "nối user (đã scope) với role dùng chung",
    "refresh_tokens": "tra theo hash token trước khi biết tenant",
    "oauth_accounts": "tra theo Google sub trước khi biết tenant",
    "auth_tokens": "token một lần tra theo hash trước khi biết tenant; lời mời mang tenant_id riêng",
    "system_settings": "cài đặt hệ thống một dòng",
    "push_keys": "khoá VAPID của hệ thống",
    "push_subscriptions": "thiết bị của một user",
    "notifications": "thuộc một user (user_id)",
    "credentials": "khoá API dùng chung của hệ thống",
    "agents": AGENT_CONFIG,
    "agent_providers": AGENT_CONFIG,
    "agent_models": AGENT_CONFIG,
    "agent_keys": AGENT_CONFIG,
    "agent_toolsets": AGENT_CONFIG,
    "agent_tool_overrides": AGENT_CONFIG,
    "agent_system_prompts": AGENT_CONFIG,
    "agent_hooks": AGENT_CONFIG,
    "agent_limits": AGENT_CONFIG,
    "orchestrator_routes": AGENT_CONFIG,
    "agent_user_limits": GUARD,
    "agent_chat_blocks": GUARD,
}
SQL_VERBS = r"\b(?:from|join|update|into|table)\s+\"?{table}\b"


def _scoped() -> dict[str, str]:
    return {m.__tablename__: m.__name__ for m in scoped_models()}


def test_every_table_is_tenant_scoped_or_a_listed_platform_table():
    scoped = _scoped()
    loose = sorted(set(SQLModel.metadata.tables) - set(scoped) - set(PLATFORM))
    assert not loose, "Rule B14: bảng chưa kế thừa TenantScoped và không phải bảng nền tảng:\n  " + "\n  ".join(loose)
    assert "users" in scoped


def test_platform_list_has_no_stale_or_scoped_entries():
    tables = set(SQLModel.metadata.tables)
    assert not set(PLATFORM) - tables, f"bảng không còn — dọn khỏi PLATFORM: {sorted(set(PLATFORM) - tables)}"
    both = set(PLATFORM) & set(_scoped())
    assert not both, f"đã TenantScoped thì bỏ khỏi PLATFORM: {sorted(both)}"


def _offenders(root: pathlib.Path = SCAN) -> list[str]:
    scoped = _scoped()
    patterns = [re.compile(SQL_VERBS.format(table=re.escape(t)), re.IGNORECASE) for t in scoped]
    classes = set(scoped.values())
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parents[1]).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr == "__table__":
                if isinstance(node.value, ast.Name) and node.value.id in classes:
                    found.append(f"{rel}:{node.lineno}  {node.value.id}.__table__")
            is_str = isinstance(node, ast.Constant) and isinstance(node.value, str)
            if is_str and any(p.search(node.value) for p in patterns):
                found.append(f"{rel}:{node.lineno}  {node.value.strip()[:80]}")
    return found


def test_no_raw_sql_or_core_table_on_tenant_scoped_tables():
    offenders = _offenders()
    assert not offenders, "Rule B14: SQL thô / bảng Core trên bảng TenantScoped (lọt bộ lọc tenant):\n  " + "\n  ".join(
        offenders
    )


def test_the_scan_catches_raw_sql(tmp_path):
    app = tmp_path / "backend" / "app"
    app.mkdir(parents=True)
    (app / "probe.py").write_text('Q = "select id from users where email = :e"\nT = User.__table__\n', encoding="utf-8")
    hits = sorted(line.split("  ")[1] for line in _offenders(app))
    assert hits == ["User.__table__", "select id from users where email = :e"]
