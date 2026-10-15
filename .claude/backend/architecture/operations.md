# Backend — `@operation`: một khai báo cho REST, agent, quyền, log

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [backend/CLAUDE.md](../CLAUDE.md) · [realtime](./realtime.md) · [observability](./observability.md) · [connections §3](./connections.md) · [platform/auth-rbac](../../platform/architecture/auth-rbac.md) · [decisions](../../platform/design/decisions/README.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0, bỏ `group_permission` + owner resolver).

Web và agent là hai client ngang hàng của **cùng một handler**, cùng kiểm quyền, cùng event log.

---

## 1. Khai báo

```python
@operation(
    "auth.login",                     # "<miền>.<việc>"
    title="Đăng nhập",
    description="…",
    effect="write",                   # read | write | destructive
    permission=None,                  # quyền hệ thống; None = mọi user đăng nhập
    superadmin=False,
    public=True,
    agent=False, agent_reason="…",    # hoặc agent=True, toolset="…", agent_hint="…"
    invalidates=("auth.me",),         # query key frontend (R18)
    read_from="ro",
)
async def login(ctx: OpContext, inp: LoginIn) -> AuthOut: ...
```

Input / output là pydantic → OpenAPI (`make openapi`, R7) + JSON Schema cho tool agent.

## 2. REST suy từ tên

| effect | Route | Input |
|---|---|---|
| `read` | `GET /bizwithagents/api/<miền>/<việc>` | query param |
| `write` / `destructive` | `POST /bizwithagents/api/<miền>/<việc>` | JSON body |

- ID trong body / query, không đặt vào path.
- `create_app` gắn mọi operation khai trong `app.*`.
- Danh sách dùng `PageIn` (`limit` 1–100, mặc định 20, `offset`) → `Page {items, total, limit, offset}` (R14).
- Route viết tay bọc `@ui_only("<lý do>")`.

## 3. Runner — `run_operation(name, principal, raw_input, *, source, agent_run_id, request_ip)`

1. Tìm spec → `1001`.
2. `public`? Không thì thiếu principal → `1004`.
3. `superadmin` → `1005`.
4. `permission` → `1005`.
5. Validate → `1002`.
6. Mở session theo `effect`.
7. Chạy handler.
8. Commit.
9. Sau commit: emit → `data:changed` → thông báo → event log (lỗi cũng ghi `ok=false`). Lỗi ở bước này chỉ log, không làm hỏng kết quả đã commit.

## 4. `OpContext`

| Trường / hàm | Ý nghĩa |
|---|---|
| `principal` | `Principal(user_id, perms, sup)` |
| `session` · `redis` · `mongo` | kết nối đúng kênh; `mongo=None` khi tắt cờ |
| `cid` · `source` · `agent_run_id` · `request_ip` | truy vết |
| `emit_to_user(s)` / `emit_to_superadmins` | sự kiện realtime, gửi sau commit |
| `invalidate(keys, users)` | `data:changed` cho người bị ảnh hưởng |
| `notify(user_id, kind, title, body, params, action)` | thông báo — [observability §5](./observability.md) |
| `after_commit(hook)` | việc chỉ chạy khi commit thành công |

## 5. Test luật (`backend/tests/rules/`)

- Thao tác ghi ở miền phía user → `agent=True`, hoặc `agent=False` + `agent_reason`.
- Route tay → `ui_only`.
- Mã lỗi đúng dải; `loc` duy nhất + đúng tiền tố; nuốt exception phải log.

## 6. Agent

`list_actions(principal)` · `call_action(name, principal, args, *, agent_run_id)` = `run_operation(..., source="agent")`.

## 7. Công cụ dev (`app/devtools/`)

| Chế độ | `devtools.raise_error` có route | Trong `openapi.json` |
|---|---|---|
| `ENV ∈ {dev, smoke}` | ✓ `POST /bizwithagents/api/devtools/raise_error` `{note?}` → 500 `1000` + `correlation_id` | ✗ |
| `ENV` khác (Coolify: `prod`) | ✗ (module không nạp, route bị gỡ) | ✗ |

→ Chỉ dùng cho smoke local / docker và E2E (`scripts/e2e_sp1.py`).
- Op: `superadmin=True`, `agent=False`.
- Choke-point (R12): `app/devtools/guard.py` (`devtools_enabled`, `guard_devtools_routes`). `load_domains()` chỉ nạp `app.devtools.ops` khi `devtools_enabled`; `create_app` bỏ qua namespace `devtools` khi ENV không cho và luôn gắn nó với `include_in_schema=False` — FastAPI 0.141 lồng route của `include_router`, nên lọc `APIRoute` ở cấp app (cách của `guard_devtools_routes`) không thấy route đó.
- Thông báo thử **không** ở đây — dùng `notifications.send_test` (superadmin, có ở mọi ENV).
- Test: `backend/tests/devtools/`, `backend/tests/test_smoke_contract.py`.

---

*Cập nhật: 2026-10-12*
