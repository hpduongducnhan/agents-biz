# CLAUDE.md — Platform

> **Backlinks:** [CLAUDE.md](../../CLAUDE.md) | [template-v1](./design/template-v1.md) · [roadmap](./design/roadmap.md)

**Trạng thái:** ĐÃ CHỐT. Platform = thiết kế tổng + phần cross-stack (backend + realtime + frontend) của template. Rule riêng từng stack: [backend](../backend/CLAUDE.md) · [frontend](../frontend/CLAUDE.md) · [deploy](../deploy/CLAUDE.md). Rule chung: [CLAUDE.md](../../CLAUDE.md) R1–R29.

## Menu tài liệu

### Architecture (`architecture/`)

| File | Trạng thái | Nội dung |
|------|-----------|----------|
| [auth-rbac](./architecture/auth-rbac.md) | ĐÃ CHỐT | Bảng auth, JWT (claim `tid`) + refresh xoay vòng, superadmin từ env, RBAC dùng chung mọi tenant (admin / member / viewer), chính sách tài khoản (tầng tenant), rate limit theo IP thật, khoá tài khoản / tenant → realtime, mã 2xxx, bảng mặc định, tài khoản test 2 tenant |
| [agent-runtime](./architecture/agent-runtime.md) | ĐÃ CHỐT | Trợ lý AI: cấu hình + credential, lượt chạy + sự kiện, tool từ `@operation`, duyệt, xoay key, hạn mức + chống spam, ngữ cảnh (registry), trace + usage, hook, router + chuyên gia (registry), mã 6xxx, bảng mặc định |
| [tenancy](./architecture/tenancy.md) | ĐÃ CHỐT | Tenant: mô hình 1 user = 1 tenant, lọc tự động `TenantScoped` (luật B14), phòng realtime, `signup_mode`, lời mời, khoá tenant, mã 2109–2115 |
| [tasks-module](./architecture/tasks-module.md) | ĐÃ CHỐT | Module mẫu Tasks + khuôn thêm module: 9 chỗ phải chạm, backend / frontend (registry D25), op, trợ lý, kiểm, bảng mặc định |
| [mail](./architecture/mail.md) | ĐÃ CHỐT | Transport console / smtp, mẫu thư theo ngôn ngữ, task gửi, xác thực email, quên mật khẩu, bảng mặc định |

### Playbook (`playbooks/`)

| File | Trạng thái | Nội dung |
|------|-----------|----------|
| [playbooks](./playbooks/README.md) | ĐÃ CHỐT | Bằng chat (Claude Code / Codex / Gemini — skill `new-app`, `setup-env`, `new-module`); tạo app sau khi clone (`make init-app`), dựng môi trường (`make setup`), kéo bản sửa của template (`make template-sync`), thêm module (`make new-module`): bước, ai làm, lỗi hay gặp |

### Design (`design/`)

| File | Trạng thái | Nội dung |
|------|-----------|----------|
| [template-v1](./design/template-v1.md) | ĐÃ CHỐT | Thiết kế tổng: mục tiêu, giữ / sửa / bỏ từ dự án nguồn, đổi tên, tenant, mail, module, agent, Tasks, i18n, môi trường, tài liệu |
| [decisions](./design/decisions/README.md) | — | Nhật ký quyết định D1… + quyết định kế thừa từ dự án nguồn |
| [roadmap](./design/roadmap.md) | — | Sub-project + trạng thái |

### Plans (`plans/`)

| File | Trạng thái | Nội dung |
|------|-----------|----------|
| [sp0-platform-port](./plans/sp0-platform-port/README.md) | Xong | Chép nền từ dự án nguồn, đổi tên `bw`, bỏ nghiệp vụ ví / nhóm / chia tiền / Drive |
| [sp1-tenant-mail](./plans/sp1-tenant-mail/README.md) | Xong | Tenant (lọc tự động, `signup_mode`, lời mời, khoá tenant, phòng realtime), mail, xác thực email, quên mật khẩu |
| [sp2-agent-general](./plans/sp2-agent-general/README.md) | Xong | Registry toolset, dữ liệu agent theo tenant, usage / trace theo tổ chức, tắt trợ lý theo tenant, stream chat + `/sa/ai-settings` (D22–D24) |
| [sp3-tasks-module](./plans/sp3-tasks-module/README.md) | Xong | Module mẫu Tasks: bảng, op, realtime, nhắc hạn, chuyên gia + câu ý định, registry module frontend (D25), UI danh sách / chi tiết / Thêm nhanh / widget |
| [sp4-scaffold](./plans/sp4-scaffold/README.md) | Xong | `make new-module` (Jinja2 theo khuôn Tasks) + `scaffold-check` trong CI, `make new-app` (đổi tên, cổng, Redis db) + `new-app-check`, skill new-module / new-app |
| [sp5-release](./plans/sp5-release/README.md) | Xong | Dọn tên / tham chiếu dự án nguồn trong code, HLD + sơ đồ, kiểm toàn bộ, tag `v1.0.0` |
| [sp6-agent-skills](./plans/sp6-agent-skills/README.md) | Xong | Skill cho Claude Code / Codex / Gemini (`.agents/skills` + `AGENTS.md`), `make init-app` đổi tên tại chỗ sau khi clone, `make setup` dựng môi trường (D26–D28); `make template-sync` kéo bản sửa của template (D29) |

---

*Cập nhật: 2026-10-15*
