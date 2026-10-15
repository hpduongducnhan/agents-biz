# Platform — Tenant: tách dữ liệu khách hàng

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [platform/CLAUDE.md](../CLAUDE.md) · [template-v1 §3.2](../design/template-v1.md) · [decisions D10–D13](../design/decisions/d01-current.md) · [auth-rbac](./auth-rbac.md) · [plan SP1](../plans/sp1-tenant-mail/README.md)

**Trạng thái:** ĐÃ CHỐT (SP1). Code: `backend/app/core/tenancy.py`, `backend/app/tenants/`, `realtime/src/` (phòng tenant).

Tenant chỉ là **ranh giới dữ liệu** (D3). RBAC, agent, Studio, thông báo giữ cách của dự án nguồn; lõi thêm **một** bộ lọc `tenant_id` tự động. Code module và agent không phải nghĩ tới tenant.

## 1. Mô hình (D10)

- Mỗi user thuộc đúng một tenant: `users.tenant_id` NOT NULL, claim `tid` trong JWT. Một email chỉ ở một tenant.
- Bảng `tenants`: `id` · `name` · `slug` (citext, unique) · `status` `active | suspended` · `policies` jsonb · `created_at` · `updated_at`. Tenant `default` có id cố định `00000000-0000-4000-8000-000000000001`, tạo ở migration.
- Bảng nghiệp vụ của module kế thừa `TenantScoped` (`tenant_id` FK + index). Nền: `users`, hội thoại trợ lý `agent_sessions` · `agent_messages` · `agent_runs` · `agent_approvals` (D22 — worker ghi tin / duyệt chép `tenant_id` của phiên / lượt). Bảng toàn nền tảng (không `tenant_id`, danh sách + lý do ở `PLATFORM` của test B14): cấu hình agent, chặn / hạn mức chat từng user, credential, permission, role, system settings, push keys, thông báo.
- Span trace + document usage (Mongo) mang `tenant_id` → `/sa/usage` gộp / lọc theo tổ chức, `/sa/traces` lọc tổ chức. Tổ chức tắt trợ lý: `policies.agent_enabled=false` ([agent-runtime §12](./agent-runtime.md)).

## 2. Lọc tự động (D11)

| Chỗ | Việc |
|---|---|
| `scope_session(session, tid)` | đặt `session.info["tenant_id"]` |
| listener `do_orm_execute` | mọi `select` / `update` / `delete` ORM có `with_loader_criteria(TenantScoped, tenant_id == tid)` (cả `session.get`, lazy load) |
| listener `before_flush` | đối tượng mới thiếu `tenant_id` → gán; đối tượng của tenant khác (mới hoặc đã sửa) → `1005` |
| runner `@operation` | scope session theo `principal.tenant_id` (op public: không scope) |
| `ctx.cross_tenant()` | bỏ lọc trong khối `with` — chỉ superadmin (`sup`), log `sys0601` |
| `tenant_session(tid)` | session đã scope cho task / consumer / cron; cron chạy cho mọi tenant thì lặp tenant tường minh |

Không đi qua bộ lọc: SQL thô (`text()`), bảng Core — test luật B14 cấm trên bảng `TenantScoped` trong module.

## 3. Realtime (D13)

- Bắt tay: service realtime join `user:<id>` + `tenant:<tid>` (claim `tid`) + `sup` nếu có.
- `ctx.invalidate(keys, tenant=True)` / `emit_to_tenant(tid, event, data)` → routing key `tenant.<tid>`. `data:changed` chỉ mang query key — client tải lại theo quyền của mình.
- Sự kiện riêng (`core:notification`, `agent:*`, `core:rbac_updated`) vẫn tới `user:<id>`.

## 4. Đăng ký vào tenant (D12)

`system_settings.signup_mode` (thay `signup_open`):

| `signup_mode` | Người đăng ký mới (không có lời mời) |
|---|---|
| `default_tenant` (mặc định) | vào tenant `default`, role `member` |
| `new_tenant` | tạo tenant mới (tên nhập ở form, mặc định theo tên người dùng), role `admin` |
| `invite_only` | bị từ chối `2105` |

- Có lời mời (`invite_token`): vào tenant + role của lời mời ở mọi chế độ. Lời mời gắn email thì email đăng ký phải trùng.
- Email trong `SUPERADMIN_EMAILS` luôn đăng ký được (tenant `default`).
- Google OAuth: user mới đi theo cùng luật; có lời mời gắn email đó đang chờ → vào tenant của lời mời.
- Hạn mức `user_limit` của tenant (0 = không giới hạn) chặn đăng ký / nhận lời mời khi đầy → `2111`.

## 5. Lời mời

`auth_tokens` (`purpose=invite`): `tenant_id` · `email` (NULL = link) · `role_id` · `max_uses` · `uses` · `expires_at` · `token_hash` (SHA-256 — token thô chỉ có trong link).

| Op | Ai | Việc |
|---|---|---|
| `tenant.invite {email? , role_id, days, max_uses}` | `tenant.invite` | email → gửi thư `invite`; không email → trả link (token thô một lần). Chưa xác thực email (chế độ `soft`) → `2112` |
| `tenant.list_invites` · `tenant.revoke_invite` | `tenant.invite` | lời mời còn hạn / thu hồi |
| `invites.preview {token}` | công khai | tên tenant, role, hạn, email gắn (che) — trang `/invite/:token` |

Email đã có tài khoản (tenant nào cũng vậy) → `2109`, không gộp tài khoản.

## 6. Khoá tenant

`tenants.suspend` (superadmin): `status=suspended` → dấu Redis `bw:tenant:disabled:<tid>` (TTL = đời access token) → thu hồi refresh token mọi user của tenant → `core:account_disabled` tới phòng tenant + `rt:revoke` từng user. REST mang token cũ → 403 `2110`; đăng nhập → `2110`. `tenants.resume` gỡ.

## 7. Mã lỗi (dải auth 2xxx)

| Mã | Ý nghĩa |
|---|---|
| 2109 | Email đã có tài khoản (không nhận lời mời / không tạo trùng) |
| 2110 | Tenant đang bị khoá |
| 2111 | Tenant đã đủ số user (`user_limit`) |
| 2112 | Cần xác thực email trước khi mời người khác |
| 2113 | Cần xác thực email trước khi đăng nhập (`email_verification=required`) |
| 2114 | Lời mời / link không hợp lệ hoặc hết hạn |
| 2115 | Không tìm thấy tenant |

## 8. Bảng mặc định (R11)

| Khoá | Mặc định | Nguồn thật |
|---|---|---|
| `signup_mode` | `default_tenant` | `/sa/settings` |
| `user_limit` | 0 (không giới hạn) | `tenants.policies` (`/sa/tenants`) → `system_settings.user_limit_default` |
| lời mời: hạn / số lần dùng | 7 ngày / email: 1, link: 20 | input `tenant.invite` |

---

*Cập nhật: 2026-10-15*
