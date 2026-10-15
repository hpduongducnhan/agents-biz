# SP1 — Tenant + mail + luồng đăng nhập

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [roadmap](../../design/roadmap.md) · [template-v1 §3.2–§3.3](../../design/template-v1.md) · [decisions D10–D14](../../design/decisions/d01-current.md) · [auth-rbac](../../architecture/auth-rbac.md)

**Trạng thái:** **Xong** (2026-10-15) — plan dạng đặc tả (D18). Kết quả ở [roadmap](../../design/roadmap.md); E2E: `scripts/e2e/sp1_tenant_ui.py` (ảnh + `result.json` ở `.e2e/sp1/`, đã gitignore).

## Goal

Dữ liệu từng khách hàng tách hẳn nhau mà code module và agent không phải nghĩ tới tenant; người dùng vào đúng tenant theo `signup_mode`; email thật cho xác thực, quên mật khẩu, lời mời.

## Architecture

**Lõi tenant** (`app/core/tenancy.py` — chỗ duy nhất của lõi biết tenant):

| Thành phần | Việc |
|---|---|
| `TenantScoped` (mixin SQLModel) | cột `tenant_id` uuid NOT NULL + index, FK `tenants.id` |
| `scope_session(session, tenant_id)` | đặt `session.info["tenant_id"]`; listener `do_orm_execute` thêm `with_loader_criteria(TenantScoped, tenant_id == …, include_aliases=True)` cho mọi `select` / `update` / `delete` ORM; listener `before_flush` gán `tenant_id` cho đối tượng mới thiếu, đối tượng khác tenant → `AppException(1005)` |
| `tenant_session(tid)` | context manager mở session RW / RO đã scope — dùng ở task / consumer / cron |
| `ctx.tenant_id` · `ctx.cross_tenant()` | runner scope session theo `principal.tenant_id`; `cross_tenant()` trả session **không** lọc, chỉ khi `principal.sup`, log `sys0601` (op, user) |
| `ctx.invalidate(keys, tenant=True)` · `emit_to_tenant(tid, event, data)` | routing key `tenant.<tid>` → phòng `tenant:<tid>` |

**Bảng** (gộp vào chuỗi migration đầu — template chưa deploy nên sửa thẳng `0002_auth_rbac`, DB dev dựng lại):

| Bảng | Cột chính |
|---|---|
| `tenants` | `id` · `name` · `slug` unique · `status` `active \| suspended` · `policies` jsonb · `created_at` |
| `users` | thêm `tenant_id` (FK, NOT NULL), `email_verified_at` |
| `auth_tokens` | `id` · `user_id` NULL · `tenant_id` · `purpose` `verify \| reset \| invite` · `token_hash` (SHA-256) · `email` · `role_id` · `max_uses` · `uses` · `expires_at` · `used_at` · `created_by` |

Tenant `default` tạo lúc `bw migrate` (bước `tenants.default`); user cũ / superadmin thuộc tenant này.

**Quyền + role** (D12): role có sẵn đổi thành `admin` · `member` · `viewer` (+ superadmin env); `member` là role mặc định; `role.manage` chỉ superadmin; quyền mới `tenant.settings`, `tenant.invite`. `admin.*` của admin tenant tự lọc theo tenant (bảng `users` là `TenantScoped`); superadmin xem chéo ở `/sa/tenants` và `/admin/users` (`cross_tenant`).

**JWT + realtime** (D13): claim `tid`; service realtime join `tenant:<tid>` lúc bắt tay, bind / unbind routing key `tenant.<tid>` như `user.<id>`.

**Đăng ký** (D12): `system_settings.signup_mode` thay `signup_open` — `default_tenant` (mặc định) · `new_tenant` (tạo tenant + role `admin`) · `invite_only`. Lời mời: email (gửi mail) hoặc link (token, hạn, số lần dùng); `auth.register` nhận `invite_token` → vào tenant + role của lời mời. Email đã có tài khoản → `2109`. Google OAuth tạo user mới theo cùng luật.

**Khoá tenant:** `tenants.suspend` → `status=suspended` + dấu Redis `bw:tenant:disabled:<tid>` (TTL = đời access token) + `rt:revoke` cho phòng tenant + thu hồi refresh token của mọi user tenant đó; REST mang token cũ → 403 `2110`.

**Chính sách:** `AccountPolicies` thêm tầng tenant (mặc định hệ thống → tenant → role lớn nhất → user); khoá mới `user_limit` (đếm user active của tenant khi đăng ký / nhận lời mời — `2111`), `agent_enabled` (SP2 đọc).

**Mail** (D14, `app/mail/`): `MailTransport` protocol · `ConsoleTransport` (log `mail0001` + Redis list `bw:mail:outbox` ≤ 50 thư, TTL 1 ngày — trang `/sa/mail`) · `SmtpTransport` (`aiosmtplib`, STARTTLS / TLS) · `render(template, locale, **ctx)` Jinja2 (`app/mail/templates/<tên>.<locale>.{html,txt}`) · task `mail.send` (lane `default`, retry 2, idempotent `bw:mail:sent:<id>`). Mã lỗi `8xxx`, `loc` `mail`.

**Luồng auth mới:** `auth.request_verify` · `auth.verify_email {token}` (public) · `auth.forgot_password {email}` (public, luôn 200, rate limit) · `auth.reset_password {token, new_password}` (public, thu hồi mọi refresh token) · `system_settings.email_verification` `off | soft | required` (mặc định `soft`: banner nhắc; chưa xác thực không mời được người khác — `2112`; `required`: chưa xác thực không đăng nhập được — `2113`).

**Op tenant:** `tenant.get` · `tenant.update` (admin: tên, cài đặt) · `tenant.invite {email \| link, role_id, max_uses, days}` · `tenant.list_invites` · `tenant.revoke_invite` · `invites.preview {token}` (public: tên tenant, role, hạn) · superadmin `tenants.list` · `tenants.create {name, admin_email}` (tạo + mời admin đầu tiên) · `tenants.update` (tên, chính sách) · `tenants.suspend` / `tenants.resume`.

## Global Constraints

- Mọi bảng mới của nền có `tenant_id` trừ: `tenants`, cấu hình agent, credential, permission, role, system settings, push keys.
- Test luật mới (B14): model trong `app/<module>/` (ngoài nền) kế thừa `TenantScoped`; không `text()` / Core trên bảng `TenantScoped` trong module (ngoại lệ ghi lý do); Redis key tenant mang `tid`.
- Seed dev: 2 tenant (`default`, `acme`) + user test mỗi tenant (`user1..3@test.local` ở `default`, `acme1@test.local` ở `acme`).

## Tasks

| # | Việc | Kết quả |
|---|---|---|
| T1 | Lõi tenancy | `core/tenancy.py`, sửa runner / `OpContext` / `Principal` (`tenant_id`), test lọc select / update / delete / get, before_flush, cross_tenant |
| T2 | Migration + model | `tenants`, `users.tenant_id` + `email_verified_at`, `auth_tokens`; bước migrate `tenants.default`; `bw migrate` trên DB trống |
| T3 | Auth + RBAC | claim `tid`, role `admin / member / viewer`, `role.manage` superadmin-only, `signup_mode`, đăng ký qua lời mời, Google theo `signup_mode`, `user_limit` |
| T4 | Realtime tenant | service realtime phòng `tenant:<tid>`, `emit_to_tenant`, `ctx.invalidate(tenant=True)`, test RT ≥ 90 % |
| T5 | Mail | `app/mail/` + mẫu thư vi / en + task + `/sa/mail` (console) + bảng mặc định R11 |
| T6 | Xác thực email + quên mật khẩu | op + `auth_tokens` + rate limit + `email_verification` |
| T7 | Op tenant + lời mời + khoá tenant | op ở trên, mã `2109–2113`, realtime khoá tenant |
| T8 | Frontend | đăng ký theo `signup_mode`, trang nhận lời mời `/invite/:token`, xác thực email, quên / đặt lại mật khẩu, banner chưa xác thực, trang **Tổ chức** (`/org`: thông tin, thành viên, lời mời), `/sa/tenants`, `/sa/mail`, tên tenant ở Header, i18n vi / en |
| T9 | Tài liệu | `auth-rbac` (tenant, role mới, luồng mới), doc mới `tenancy.md`, `mail.md`, B14 vào backend/CLAUDE.md, roadmap |
| T10 | Kiểm + release | `make ci`; smoke-local thêm bước 2 tenant (user `acme` không thấy dữ liệu `default` qua REST lẫn socket), quên mật khẩu qua outbox console; E2E Playwright (subagent) 375 / 1440 |

## Definition of Done

- `make ci` xanh; `make dev-up` + `make smoke-local` hai chế độ Mongo xanh, có bước tách tenant.
- Test: user tenant B gọi op đọc / sửa dữ liệu tenant A → 404 / 1005; socket tenant B không nhận `data:changed` của tenant A.
- E2E: đăng ký 3 chế độ, mời bằng link, đặt lại mật khẩu, khoá tenant → bị đăng xuất.

## Self-Review

- Agent: bảng chat / run / approval thành `TenantScoped` ở SP2 (cùng lúc với registry) — ghi rõ ở SP2 plan.
- Superadmin dùng trợ lý: principal agent `sup=False` → luôn trong tenant của mình.
- Sau E2E: trang `/invite/:token` gọi preview một lần ngoài cache query (đăng nhập `resetQueries` từng gọi lại preview với token đã dùng → 400). Theo dõi: một lần E2E T1 375 bị đẩy về `/login` kèm `401 auth/refresh` ngay sau đăng nhập — chạy lại 3 lần không tái hiện.
- Tenant tạo bởi smoke / E2E (`Smoke *`, `E2E Org *`) dồn dần trong namespace `bizwithagents_e2e` — chưa có op xoá tenant (cân nhắc ở SP5).

---

*Cập nhật: 2026-10-15*
