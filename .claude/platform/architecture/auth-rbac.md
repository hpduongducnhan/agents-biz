# Platform — Auth, RBAC hệ thống, superadmin từ env

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [decisions](../design/decisions/README.md) · [backend/operations](../../backend/architecture/operations.md) · [backend/realtime](../../backend/architecture/realtime.md) · [frontend/CLAUDE.md](../../frontend/CLAUDE.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0, SP1 thêm tenant — D10–D12). Mỗi user thuộc một tenant ([tenancy](./tenancy.md)); role và quyền dùng chung mọi tenant. Xác thực email / quên mật khẩu: [mail](./mail.md).

---

## 1. Bảng (Postgres, migration `0002_auth_rbac`)

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `users` (`TenantScoped`) | `id` uuid · `tenant_id` · `email` citext unique · `email_verified_at` · `password_hash` · `name` · `is_active` · `is_superadmin` · `must_change_password` · `timezone` · `locale` · `policies` jsonb · `created_at` · `last_login_at` | `is_superadmin` chỉ do `SUPERADMIN_EMAILS` đồng bộ |
| `oauth_accounts` | `user_id` · `provider` · `provider_uid` · `email` | Google |
| `refresh_tokens` | `id` · `user_id` · `token_hash` (SHA-256) · `family_id` · `expires_at` · `revoked_at` | xoay vòng theo họ |
| `permissions` | `codename` PK · `domain` · `description` · `deprecated_at` | đồng bộ idempotent lúc `bw migrate` |
| `roles` · `role_permissions` · `user_roles` | role (`name` unique, `is_builtin`, `policies` jsonb) · quyền của role · role của user | role dùng chung mọi tenant |
| `auth_tokens` | `purpose` `verify \| reset \| invite` · `token_hash` · `user_id` / `tenant_id` · `email` · `role_id` · `max_uses` · `uses` · `expires_at` | token một lần (thư xác thực, đặt lại mật khẩu, lời mời) |

## 2. Token

- **Access:** JWT EdDSA, claims `{sub, tid, typ: "access", perms, sup, iat, exp}` — `tid` = tenant của user; `perms` rỗng khi `sup`.
- **Refresh:** ngẫu nhiên, DB giữ SHA-256, **xoay vòng** mỗi lần dùng.
  - Token cũ bị dùng lại sau `AUTH_REFRESH_REUSE_GRACE_SECONDS` → thu hồi cả họ.
  - Trong khoảng grace (hai tab cùng refresh) thì không thu hồi.
- **Khoá ký:** `bw keys` sinh Ed25519 vào `.secrets/` (local); Coolify: PEM trong env `AUTH_PRIVATE_KEY` / `AUTH_PUBLIC_KEY`, sinh bằng `bw keys --print`; `realtime` chỉ cần public key.
- Đổi mật khẩu / đăng xuất mọi nơi → thu hồi mọi refresh token.

## 3. Superadmin từ env

- `SUPERADMIN_EMAILS` là **nguồn sự thật duy nhất**: đồng bộ lúc `bw migrate` và mỗi lần đăng ký / đăng nhập / refresh. Không API nào sửa (`2204`).
- Email trong danh sách luôn đăng ký được (tenant `default`), kể cả khi `signup_mode=invite_only`.
- `sup` vượt mọi kiểm quyền. Việc chỉ superadmin làm được: `@operation(superadmin=True)` — op này chạy không lọc tenant; op `sup_all_tenants=True` (vd `admin.list_users`) bỏ lọc khi superadmin gọi, user thường vẫn chỉ thấy tenant mình.

## 4. RBAC (dùng chung mọi tenant — D12)

| Quyền | Cho phép |
|---|---|
| `user.view` | Xem user **của tenant mình**, xem role |
| `user.manage` | Khoá / mở, gán role, đặt lại mật khẩu (trong tenant) |
| `tenant.settings` | Đổi tên tenant |
| `tenant.invite` | Mời người vào tenant (email / link), xem + thu hồi lời mời |
| `agent.chat` | Chat với agent |
| `agent.<toolset>` | Trợ lý được dùng nhóm tool tương ứng — thiếu thì tool không đưa cho LLM. Nền có `agent.lookup`; module khai toolset thì quyền tự vào catalog (SP2) |
| `<module>.*` | Quyền của module nghiệp vụ, khai bằng `declare_permissions` |

| Role có sẵn | Quyền |
|---|---|
| `superadmin` | ngầm mọi quyền (claim `sup`), theo env |
| `admin` | quản trị tenant: `user.*`, `tenant.*`, `agent.chat` + mọi `agent.<toolset>` — người tự tạo tenant (`new_tenant`) nhận role này |
| `member` | `agent.chat` + mọi `agent.<toolset>` + quyền module khai cho `member` — tự gán cho user mới (`DEFAULT_ROLE`) |
| `viewer` | `agent.chat` + mọi `agent.<toolset>` + quyền chỉ đọc module khai cho `viewer` |

- Module khai quyền + role có sẵn nhận quyền nào: `declare_permissions("tasks", {...}, roles={"admin": [...], "member": [...], "viewer": [...]})`; `bw migrate` đặt quyền role có sẵn đúng như code.
- Role tự tạo: **chỉ superadmin** tạo / sửa / xoá (role dùng chung mọi tenant), chọn quyền từ catalog. Admin tenant xem role (`user.view`) và gán role cho user của mình. Role có sẵn không sửa / xoá (`2202`); role đang gán không xoá (`2205`); `rbac.list_roles` đếm người giữ role trong tenant người xem.
- Quyền đổi → `core:rbac_updated` tới user bị ảnh hưởng → frontend refresh token + tải lại `me` → menu đổi không tải lại trang.

### 4.1 Chính sách tài khoản

Giá trị (không phải bật / tắt) gắn theo role **và** ghi đè theo user: cột jsonb `roles.policies` / `users.policies` chỉ chứa khoá đã đặt, đọc bằng `app/auth/policies.py` `AccountPolicies` (khoá hỏng → bỏ qua + `WARNING` `auth0601`).

| Khoá | Kiểu | Hiệu lực (dừng ở tầng đầu có giá trị) | Dùng ở |
|---|---|---|---|
| `chat_per_minute` · `chat_per_hour` · `chat_per_day` | int 0–100 000, `0` = không giới hạn | superadmin miễn → user ghi đè → **lớn nhất** trong các role (`0` thắng) → `system_settings.chat_per_*` (10 / 100 / 400, `/sa/chat-guard`) | `agent.send` (6001 `scope=account`), `agent.chat_limits` |

- Chỉ superadmin sửa: `rbac.set_role_policies` (cả role có sẵn), `admin.set_user_policies` (user là superadmin → 2204), xem `admin.user_policies`.
- Đổi chính sách → `data:changed` `agent.chat_limits` tới user bị ảnh hưởng (R18). Log `auth0602` / `auth0603`.
- Tầng tenant (`tenants.policies`, superadmin sửa ở `/sa/tenants`): `chat_per_*` nằm giữa mặc định hệ thống và role; `user_limit` (0 = không giới hạn, mặc định `system_settings.user_limit_default`) chặn đăng ký / nhận lời mời khi đầy (`2111`); `agent_enabled` (SP2 đọc).

## 5. Đăng ký / đăng nhập + bảng mặc định (R11)

| Key | Mặc định | Nguồn thật khi cấu hình |
|---|---|---|
| `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | env |
| `AUTH_REFRESH_TOKEN_EXPIRE_DAYS` | 7 | env |
| `AUTH_PASSWORD_MIN_LENGTH` | 8 (`2107`) | env |
| `AUTH_LOGIN_RATE_LIMIT` | 5 lần / 60 giây theo IP + email, **tính cả lần đúng** | env |
| `AUTH_REGISTER_RATE_LIMIT` / `_WINDOW` | 10 lần / 3600 giây theo IP | env |
| `AUTH_REFRESH_REUSE_GRACE_SECONDS` | 10 | env |
| `signup_mode` | `default_tenant` (`new_tenant` · `invite_only`) — [tenancy §4](./tenancy.md) | `/sa/settings` |
| `email_verification` | `soft` (`off` · `required`) — [mail](./mail.md) | `/sa/settings` |
| `user_limit_default` | `0` (không giới hạn) | `/sa/settings` |
| `AUTH_VERIFY_TOKEN_HOURS` · `AUTH_RESET_TOKEN_MINUTES` | 24 · 60 | env |
| `AUTH_EMAIL_RATE_LIMIT` | 5 thư / giờ theo IP + email (xác thực, quên mật khẩu) | env |
| `SEED_PASSWORD` | `password123` (chỉ dev / E2E) | `.env` |

- Vượt hạn mức → 429 `1007` kèm `retry_after_sec`.
- Mật khẩu argon2id; user không tồn tại vẫn so với hash giả.
- **IP** = `ctx.request_ip`; uvicorn tin `X-Forwarded-For` từ proxy:
  - deploy: nginx đặt header từ `CF-Connecting-IP`;
  - local: proxy Vite chuyển nguyên header.
  - Smoke kiểm cả hai ([deploy, mục Smoke](../../deploy/CLAUDE.md)).
- **Google OAuth:** PKCE S256, state Redis 10 phút, bắt buộc `email_verified`, route tay `ui_only`. Bật khi có `GOOGLE_CLIENT_ID` + công tắc `google_enabled` (thiếu → `2108`).

## 6. Khoá tài khoản

`admin.update_user {user_id, is_active: false}` (cần `user.manage`; không tự khoá mình — `2206`; không khoá superadmin — `2204`):
1. `is_active=false` + thu hồi refresh token (cùng transaction).
2. Sau commit: dấu Redis `bw:auth:disabled:<uid>` sống bằng đời access token → REST mang token cũ → 403 `2103`.
3. Sau commit: `rt:revoke` → mọi instance realtime ngắt socket + từ chối token cũ.
4. `core:account_disabled` → frontend đăng xuất về `/login`.

Khoá cả tenant (`tenants.suspend`, superadmin): mọi user của tenant bị chặn đăng nhập / refresh (`2110`), dấu Redis chặn access token cũ, `rt:revoke` ngắt socket.

Kiểm: smoke bước "khoá user" · E2E F4.

## 7. Mã lỗi (2xxx)

| Mã | Ý nghĩa | | Mã | Ý nghĩa |
|---|---|---|---|---|
| 2101 | Email đã đăng ký | | 2201 | Tên role đã tồn tại |
| 2102 | Sai email hoặc mật khẩu (401) | | 2202 | Role có sẵn không sửa / xoá được |
| 2103 | Tài khoản bị khoá (403) | | 2203 | Quyền không tồn tại |
| 2104 | Refresh token không hợp lệ / hết hạn | | 2204 | Superadmin do env quản |
| 2105 | Đăng ký đang đóng | | 2205 | Role đang được gán |
| 2106 | Mật khẩu hiện tại sai | | 2206 | Không tự khoá chính mình |
| 2107 | Mật khẩu quá ngắn | | 2109–2115 | Tenant / lời mời / xác thực email — [tenancy](./tenancy.md) |
| 2108 | Đăng nhập Google không khả dụng | | | |

## 8. Operation (từ `openapi.json`)

| REST | Việc |
|---|---|
| `GET /admin/get_user` | Chi tiết user |
| `GET /admin/user_policies` | Hạn mức của user |
| `POST /admin/set_user_policies` | Đặt hạn mức cho user |
| `GET /admin/list_users` | Danh sách user |
| `POST /admin/reset_password` | Đặt lại mật khẩu |
| `POST /admin/update_user` | Sửa tài khoản |
| `POST /auth/change_password` | Đổi mật khẩu |
| `GET /auth/google/authorize` | Google Authorize |
| `GET /auth/google/callback` | Google Callback |
| `POST /auth/login` | Đăng nhập |
| `POST /auth/logout` | Đăng xuất |
| `POST /auth/logout_all` | Đăng xuất mọi nơi |
| `GET /auth/me` | Hồ sơ của tôi |
| `POST /auth/refresh` | Làm mới phiên |
| `POST /auth/register` | Đăng ký |
| `POST /auth/update_me` | Sửa hồ sơ |
| `POST /auth/request_verify` · `POST /auth/verify_email` | Gửi lại thư xác thực · xác thực bằng token |
| `POST /auth/forgot_password` · `POST /auth/reset_password` | Gửi link đặt lại mật khẩu (luôn trả OK) · đặt mật khẩu mới bằng token |
| `POST /rbac/create_role` | Tạo role (superadmin) |
| `POST /rbac/delete_role` | Xoá role (superadmin) |
| `GET /rbac/list_permissions` | Catalog quyền |
| `GET /rbac/list_roles` | Role (đếm người giữ trong tenant) |
| `POST /rbac/update_role` | Sửa role (superadmin) |
| `POST /rbac/set_role_policies` | Đặt hạn mức cho role |

## 9. Frontend

- **Guard:** `ProtectedRoute` · `RequirePermission` · `RequireSuperadmin`; thiếu quyền → `/403`. Ẩn menu chỉ là UX.
- **Token:** access trong bộ nhớ; refresh `localStorage` `bw_refresh_token`; refresh single-flight + Web Locks (hai tab không gửi lại token đã xoay).
- **Realtime:** `core:rbac_updated` → refresh; `core:account_disabled` → đăng xuất.
- **Trang công khai:** `/forgot-password` · `/reset-password?token=` · `/verify-email?token=` · `/invite/:token`. Banner nhắc xác thực trong khung app khi `email_verification ≠ off` và `me.email_verified=false`; menu người dùng hiện tên tenant.

## 10. Tài khoản test (dev) — `bw seed-test-users`

| Email | Tenant | Role | Ghi chú |
|---|---|---|---|
| `superadmin@test.local` | `default` | superadmin | phải nằm trong `SUPERADMIN_EMAILS` của môi trường chạy seed — stack thử đặt sẵn; thiếu thì cảnh báo `auth0402` |
| `admin@test.local` | `default` | admin | |
| `user1@test.local` · `user2@test.local` | `default` | member | |
| `user3@test.local` | `default` | viewer | |
| `acme-admin@test.local` | `acme` | admin | tenant thứ hai — luôn kiểm được việc tách dữ liệu |
| `acme1@test.local` | `acme` | member | |

- Mật khẩu `SEED_PASSWORD`. Từ chối khi `ENV=prod` **hoặc** tên DB đích không kết thúc `_test` / `_e2e` / `_dev` (`seed_target_problem`): `.env` dev trỏ vào DB thật, không bao giờ seed vào đó.
- Chạy lại: đặt lại mật khẩu, mở khoá, đã xác thực email, bỏ `must_change_password`, đảm bảo role. `make dev-up` gọi mỗi lần.

---

*Cập nhật: 2026-10-15*
