# BizWithAgents — Thiết kế mức cao (HLD)

> **Backlinks:** [CLAUDE.md](../../CLAUDE.md) | [template-v1](../platform/design/template-v1.md) · [decisions](../platform/design/decisions/README.md) · [tenancy](../platform/architecture/tenancy.md) · [agent-runtime](../platform/architecture/agent-runtime.md) · [tasks-module](../platform/architecture/tasks-module.md) · [deploy](../deploy/CLAUDE.md)

**Trạng thái:** ĐÃ CHỐT (vẽ theo code ở tag `v1.0.0`)

Bộ sơ đồ mức cao cho người mới đọc template. Tên service, cổng, exchange / queue, operation, trạng thái lấy đúng từ code và tài liệu kiến trúc (link ở mỗi mục).

**Cách đọc:**
- Mỗi sơ đồ có spec `diagrams/<tên>.<loại>.json` (archify), và trang tương tác `diagrams/<tên>.html` (pan / zoom, tìm, sáng / tối). Đổi spec → `make diagrams`; bản HTML của file này ([HLD.html](HLD.html)) nhúng sẵn sơ đồ (R23).
- Chữ trong sơ đồ tiếng Việt; thanh công cụ của viewer tiếng Anh (archify chỉ có `en` / `zh-CN`).

---

## 1. Tổng quan

| Thành phần | Công nghệ | Việc |
|---|---|---|
| `bw-web` | nginx + bundle React 19 (PWA) | cửa duy nhất: SPA, `/bizwithagents/api/*` → api, `/bizwithagents/ws/*` → realtime |
| `bw-api` | FastAPI · `@operation` | REST (envelope R6), `bw migrate` khi khởi động |
| `bw-consumer` · `bw-worker` · `bw-scheduler` | FastStream · taskiq | subscriber + lượt chạy trợ lý · task nền · cron (leader qua Redis) |
| `bw-realtime` | Node + Socket.IO | phòng `user:<id>` · `tenant:<tid>` · `sup`; nhận `bw.rt.out` từ RabbitMQ |
| Postgres · Redis · RabbitMQ · Mongo (tuỳ chọn) | hạ tầng chung trên server (D19) | dữ liệu theo tenant · cache / khoá / hạn mức · message · log + trace |

Một hành động người dùng = một `@operation` chạy chung cho web, socket và trợ lý: kiểm quyền → scope tenant → validate → handler → commit → sau commit (realtime, thông báo, event log).

## 2. Triển khai trên Coolify

```archify
diagrams/deployment.architecture.json
```

[Mở HTML](diagrams/deployment.html)

- Người dùng → Cloudflare → Traefik (Coolify) → `bw-web`; chỉ `bw-web` có domain (`SERVICE_URL_BW_WEB`), không service nào publish cổng host. Cổng container 16811–16813.
- `bw-api` chạy `bw migrate && exec bw api` (Alembic một chuỗi, đồng bộ quyền + superadmin, seed trợ lý — chạy lại vô hại); consumer / worker / scheduler chờ api healthy.
- Khoá JWT là PEM trong env (`bw keys --print`); realtime chỉ cần public key.
- Hạ tầng dùng chung, tách namespace từng app: DB `bizwithagents` (+ `_test`, `_e2e`), vhost cùng tên, Redis db riêng + tiền tố `bw:`, Mongo DB riêng (D19). App mới: clone rồi `make init-app` đổi cả bộ tên tại chỗ (D27), `make setup` dựng môi trường (D28), `make template-sync` kéo bản sửa của template về sau (D29) — làm bằng chat qua skill cho Claude Code / Codex / Gemini (D26, [playbooks](../platform/playbooks/README.md)).
- Deploy = push `main` → Coolify kéo về (R27); `make deploy` là đường dự phòng (UC-e).

## 3. Dữ liệu và kết nối

### 3.1 Postgres + Redis

```archify
diagrams/data-postgres-redis.architecture.json
```

[Mở HTML](diagrams/data-postgres-redis.html)

- Postgres: kênh RW / RO, một driver `psycopg3` (B2). Bảng nghiệp vụ + hội thoại trợ lý kế thừa `TenantScoped` — lọc / gán `tenant_id` tự động ([tenancy](../platform/architecture/tenancy.md), B14).
- Redis: cache cài đặt, hạn mức (Lua), dấu khoá tài khoản / tổ chức, leader cron, outbox thư console, khoá idempotent của task.

### 3.2 RabbitMQ

```archify
diagrams/data-rabbitmq.architecture.json
```

[Mở HTML](diagrams/data-rabbitmq.html)

- Một broker, vhost riêng; tên `bw.*`. Lane taskiq cố định (`agent-run` riêng cho lượt chạy trợ lý); subscriber FastStream cho sự kiện; `bw.rt.out` (topic) đưa sự kiện realtime tới service Node theo routing key `user.<id>` / `tenant.<tid>` / `sup` / `all`.

### 3.3 Mongo (chỉ log) + dịch vụ ngoài

```archify
diagrams/data-mongo-external.architecture.json
```

[Mở HTML](diagrams/data-mongo-external.html)

- Mongo chỉ cho event log, issue, trace + usage trợ lý; `MONGO_ENABLED=false` → sink no-op, app chạy đủ (R12).
- Ngoài: nhà cung cấp LLM (key mã hoá Fernet, xoay vòng), SMTP (thư — D14), Google OAuth, Web Push.

## 4. Kiến trúc logic

```archify
diagrams/logical-layers.architecture.json
```

[Mở HTML](diagrams/logical-layers.html)

- Frontend: trang lõi + module (registry `src/modules` — D25), TanStack Query với query key theo tiền tố operation; `data:changed` từ socket → làm mới đúng phần (R18).
- Backend: miền lõi (`system`, `auth`, `tenants`, `mail`, `observability`, `notifications`, `credentials`, `agent`) + module (`tasks`, và module sinh bằng `make new-module`). Mỗi miền: model · schemas · service · ops · permissions · agent.
- Trợ lý gọi tool = gọi đúng `@operation` dưới quyền của người chat — không có đường tắt quyền / tenant.

## 5. Luồng use case

### 5a. Đăng nhập, socket, refresh, bị khoá

```archify
diagrams/uc-login-session.sequence.json
```

[Mở HTML](diagrams/uc-login-session.html)

JWT EdDSA có claim `tid`; refresh xoay vòng theo họ; khoá tài khoản có hiệu lực ngay (dấu Redis + `rt:revoke`) — [auth-rbac](../platform/architecture/auth-rbac.md).

### 5b. Mời vào tổ chức, đăng ký, khoá tổ chức

```archify
diagrams/uc-tenant-invite.sequence.json
```

[Mở HTML](diagrams/uc-tenant-invite.html)

Lời mời email / link (token một lần, hạn, số lần dùng), thư qua task `mail.send`, đăng ký vào đúng tổ chức + vai trò; superadmin khoá tổ chức → mọi người trong tổ chức bị đăng xuất ngay — [tenancy](../platform/architecture/tenancy.md), [mail](../platform/architecture/mail.md).

### 5c. Một lượt chat với trợ lý

```archify
diagrams/uc-agent-turn.sequence.json
```

[Mở HTML](diagrams/uc-agent-turn.html)

`agent.send` ghi tin + lượt `queued` rồi trả ngay; lane `agent-run` chạy router → chuyên gia → tool; chữ stream qua socket (hoặc gọi một lần khi tắt stream — D23); thao tác nguy hiểm dừng chờ duyệt — [agent-runtime](../platform/architecture/agent-runtime.md).

### 5d. Tạo việc — người cùng tổ chức thấy ngay

```archify
diagrams/uc-task-realtime.sequence.json
```

[Mở HTML](diagrams/uc-task-realtime.html)

Khuôn của mọi module: ghi trong session đã scope tenant, `data:changed` tới phòng tổ chức, thông báo người liên quan, cron đọc chéo tổ chức là ngoại lệ duy nhất — [tasks-module](../platform/architecture/tasks-module.md).

### 5e. Deploy

```archify
diagrams/uc-deploy.sequence.json
```

[Mở HTML](diagrams/uc-deploy.html)

Push `main` → Coolify build 3 image → api migrate → các service khác lên khi api healthy → smoke qua domain thật (`make smoke-prod`) — [deploy](../deploy/CLAUDE.md).

## 6. Vòng đời một lượt chạy trợ lý

```archify
diagrams/agent-run-state.lifecycle.json
```

[Mở HTML](diagrams/agent-run-state.html)

`queued → running → done | failed | cancelled`, nhánh `waiting_approval` giữ checkpoint tới khi mọi yêu cầu duyệt đã quyết hoặc hết hạn; dọn lượt treo bằng cron.

---

*Cập nhật: 2026-10-15*
