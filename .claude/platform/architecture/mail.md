# Platform — Mail + xác thực email + quên mật khẩu

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [platform/CLAUDE.md](../CLAUDE.md) · [template-v1 §3.3](../design/template-v1.md) · [decisions D14](../design/decisions/d01-current.md) · [tenancy](./tenancy.md) · [auth-rbac](./auth-rbac.md)

**Trạng thái:** ĐÃ CHỐT (SP1). Code: `backend/app/mail/` (transport, render, task, ops, `templates/`), luồng auth ở `backend/app/auth/`.

## 1. Gửi thư

| Thành phần | Việc |
|---|---|
| `get_transport(settings)` | choke-point (R12): `smtp` khi `MAIL_TRANSPORT=smtp` **và** có `SMTP_HOST`; còn lại `console` + `WARNING mail0003 DEFAULTS_APPLIED=[mail_transport]` một lần mỗi process |
| `ConsoleTransport` | log `mail0001` + Redis `bw:mail:outbox` (≤ `MAIL_OUTBOX_MAX`, TTL 1 ngày) → op `mail.outbox` (superadmin) + trang `/sa/mail` |
| `SmtpTransport` | `aiosmtplib` (STARTTLS hoặc TLS ngầm), `From = MAIL_FROM`, `Message-ID = <id@SERVICE_PATH>`, phần chữ + HTML |
| `render(template, locale, **ctx)` | Jinja2: `templates/<tên>.<locale>.txt` (dòng đầu `Subject: …`) + `.html` tuỳ chọn (autoescape); thiếu locale → `vi`; thiếu mẫu → `8001` |
| `queue_mail(to, template, locale, **ctx)` | dựng thư + `mail.send.kiq` — trong op gọi qua `ctx.after_commit` |
| task `mail.send` | lane `default`, retry 2, idempotent theo `id` (`bw:mail:sent:<id>` 7 ngày); lỗi transport → `mail0501` + ném lại |

Mẫu có sẵn: `verify_email`, `reset_password`, `invite` (vi / en). Biến chung: `app_name`, `link`, `button`.

## 2. Xác thực email

- `users.email_verified_at`; user Google mới và user vừa đặt lại mật khẩu qua email coi như đã xác thực.
- Đăng ký (chế độ khác `off`) → token `verify` (24 giờ) + thư. `auth.request_verify {email}` (công khai, luôn 200, rate limit) gửi lại. `auth.verify_email {token}` (công khai) → đặt `email_verified_at`, token dùng một lần.
- `system_settings.email_verification`: `off` · **`soft`** (mặc định — đăng nhập được, banner nhắc, chưa xác thực không mời được người khác `2112`) · `required` (chưa xác thực không đăng nhập được `2113`).

## 3. Quên mật khẩu

- `auth.forgot_password {email}` (công khai): luôn 200, rate limit theo IP + email; user tồn tại → token `reset` (60 phút, dùng một lần) + thư.
- `auth.reset_password {token, new_password}` (công khai): kiểm chính sách mật khẩu, đặt mật khẩu, thu hồi mọi refresh token, xác thực email, đánh dấu token đã dùng. Token sai / hết hạn / đã dùng → `2114`.

## 4. Link trong thư

`app_base_url(settings)`: `PUBLIC_URL` → origin của `FRONTEND_AUTH_CALLBACK_URL` → `CORS_ALLOW_ORIGINS[0]`; đang dùng dự phòng thì `WARNING mail0006 DEFAULTS_APPLIED=[app_base_url]`. Đường dẫn frontend: `/verify-email?token=…`, `/reset-password?token=…`, `/invite/<token>`.

## 5. Bảng mặc định (R11)

| Khoá | Mặc định | Nguồn thật |
|---|---|---|
| `MAIL_TRANSPORT` | `console` | env |
| `MAIL_FROM` | `BizWithAgents <no-reply@bizwithagents.local>` | env |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_STARTTLS` / `SMTP_SSL` | — / 587 / bật / tắt | env |
| `email_verification` | `soft` | `/sa/settings` |
| `AUTH_VERIFY_TOKEN_HOURS` / `AUTH_RESET_TOKEN_MINUTES` | 24 / 60 | env |

---

*Cập nhật: 2026-10-15*
