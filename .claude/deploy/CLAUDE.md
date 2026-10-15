# Deploy — BizWithAgents

> **Backlinks:** [CLAUDE.md](../../CLAUDE.md) | [coolify](./design/coolify.md) · [decisions D19](../platform/design/decisions/d01-current.md)

**Trạng thái:** ĐÃ CHỐT (D19 — mô hình triển khai giống dự án nguồn, mặc định cho mọi app làm từ template).

| Mục | Link |
|-----|------|
| **Runbook Coolify** | [coolify](./design/coolify.md) — service, image, env, namespace trên hạ tầng chung, mạng một cửa, `make deploy` |
| **Quét trước khi push** | [mục dưới](#quét-secret--tên-riêng-trước-khi-push-d30) — `make secrets-scan` (D30) |

## Mô hình (D19)

- **Hạ tầng có sẵn trên server** (`<server-ip>`): Postgres (prod đi qua PgBouncer `6432`), Redis, RabbitMQ, Mongo. App **không** mang DB theo.
- **Coolify chỉ deploy phần application**: 6 service trong `compose.yml`, mạng riêng, nối hạ tầng qua IP host.
- Mỗi app một **namespace** trên hạ tầng chung: DB `<slug>` / `<slug>_test` / `<slug>_e2e`, vhost cùng tên, một bộ Redis db riêng (dev / prod · test · stack thử), Mongo DB `<slug>`, tiền tố key / exchange `<prefix>:` / `<prefix>.`.
- Dev local nối **cùng** hạ tầng chung, `.env` trỏ cùng DB với bản deploy (dữ liệu thật — cẩn thận `make migrate`). Máy chưa có hạ tầng (máy mới, người clone): `make setup` (D28 — mặc định `MODE=local`: `make infra-up` với `deploy/compose.infra.yml` cổng 15432 / 16379 / 5673 / 27018, `.env` từ các dòng `# compose:`, khoá, migrate). App làm từ template dời các cổng này +100 × (`PORTS` − 82) nên hạ tầng local của nhiều app chạy cùng lúc được — [playbooks](../platform/playbooks/README.md).

## Service

| Service | Image | Lệnh | Cổng nội bộ | Health |
|---|---|---|---|---|
| `bw-api` | backend | `bw migrate && exec bw api` | 16812 | `/bizwithagents/api/health/ready` |
| `bw-consumer` | backend | `bw consume` | — | nhịp tim `bw:hb:consume` |
| `bw-worker` | backend | `bw work` | — | nhịp tim `bw:hb:work` |
| `bw-scheduler` | backend | `bw schedule` | — | nhịp tim `bw:hb:schedule` (1 bản — khoá leader) |
| `bw-realtime` | realtime | `node src/main.ts` | 16813 | `/bizwithagents/ws/health` |
| `bw-web` | web | nginx | 16811 | `wget /` — **cửa duy nhất**, có domain |

Stack chạy mạng riêng (tắt Connect To Predefined Network), nối hạ tầng chung qua `<server-ip>`. Khoá JWT là PEM trong env `AUTH_PRIVATE_KEY` / `AUTH_PUBLIC_KEY`, sinh bằng `bw keys --print`. Cổng container dải 168xx (mỗi app một dải — `make new-app`), Traefik vẫn 80 / 443 — [coolify §2, §4](./design/coolify.md).

## Namespace của template

| Thành phần | Giá trị |
|---|---|
| Postgres | DB `bizwithagents` (dev = prod) · `bizwithagents_test` · `bizwithagents_e2e` |
| Mongo | DB `bizwithagents` · `bizwithagents_test` · `bizwithagents_e2e` |
| Redis | db **10** (dev = prod) · **11** (test) · **12** (stack thử), key tiền tố `bw:` — chọn db còn trống trên hạ tầng chung (`INFO keyspace`) |
| RabbitMQ | vhost `bizwithagents` · `bizwithagents_test` · `bizwithagents_e2e`, user `bizwithagents` |
| Cổng local | frontend **8201** · api **8202** · realtime **8203** · docker smoke 8204 |
| Chạy | `make api` · `make realtime` · `make fe-dev` → mở `http://localhost:8201`. `make consume` / `work` / `schedule` local sẽ nhận việc của bản deploy — chỉ chạy khi cần |
| Stack chạy thử | `make dev-up MONGO=on\|off` · `make dev-status` · `make dev-down` — namespace **`bizwithagents_e2e`**, Redis db 12, khoá JWT riêng ở `.dev-stack/keys/`, superadmin `superadmin@test.local`; web `127.0.0.1:8201` (bundle build + proxy); log + pid ở `.dev-stack/` — dùng cho smoke-local và E2E, **không** đụng dữ liệu thật |
| Tài khoản test | `bw seed-test-users` — [platform/auth-rbac §10](../platform/architecture/auth-rbac.md); chỉ chạy trên DB `_test` / `_e2e` / `_dev` (`make dev-up` tự chạy) |

**Việc chờ chủ dự án:** tạo namespace `bizwithagents*` trên hạ tầng chung (Postgres cần quyền tạo DB — Claude không đọc secret của app khác). Trong lúc chờ, `.env` local trỏ `deploy/compose.infra.yml`.

`.env` (không commit, quyền 600): bản deploy sinh từ `.secrets/prod.env` (host `127.0.0.1`, Postgres nối thẳng 5432). Test tự chuyển sang `*_test` và chặn tên khác. MCP DB của dự án khai ở `.mcp.json` (không commit — có token / mật khẩu).

## Bản deploy

| Mục | Giá trị |
|---|---|
| Server Coolify | `https://coolify.<domain>` (server `<server-ip>`) |
| Repo | GitHub private `<owner>/<slug>`, branch `main` — chủ dự án tạo; GitHub App của Coolify được cấp quyền repo |
| Project / environment | `<slug>` / `production` |
| Application uuid | ghi ở `.secrets/coolify.env` (`COOLIFY_APP_UUID`) — không ghi vào tài liệu |
| Env | `.secrets/prod.env` (không commit) — toàn bộ biến production, dán vào Coolify bằng Developer view |
| Domain | `http://<slug>.<domain>` gắn cho `bw-web`, không kèm cổng (image web chỉ mở `16811`); trình duyệt dùng `https://` (Cloudflare) |
| Tunnel | Cloudflare Tunnel → public hostname `<slug>.<domain>` → `http://<server-ip>:80` |
| Deploy | commit + push `main` → webhook GitHub App → Coolify tự deploy (R27); `make deploy` chỉ dự phòng (cần `.secrets/coolify.env`) |

Không ghi mật khẩu, token, URL có mật khẩu, domain / IP thật vào file này — `<domain>` / `<server-ip>` là chỗ giữ, giá trị thật ở `.secrets/`. Bài học lần deploy đầu của dự án nguồn (đã sửa sẵn trong template): env bắt buộc rỗng thì `bw-api` dừng ở `bw migrate`; PEM trong env có thể bị lưu thành `\\n`; Traefik chọn nhầm cổng 80 nếu image web mở nhiều cổng; webhook GitHub App phải trỏ đúng domain Coolify.

## Quét secret + tên riêng trước khi push (D30)

`make secrets-scan` (nằm trong `make ci`) — `scripts/secrets_scan.sh`, thoát 1 khi có phát hiện:

| Bước | Công cụ | Phạm vi |
|---|---|---|
| Secret | **gitleaks** (luật mặc định + ngoại lệ ở `.gitleaks.toml`) | lịch sử git mọi nhánh / tag + thay đổi chưa commit (staged và chưa staged) |
| Tên riêng | `git grep` / `git log -p` theo `.secrets/private-terms.txt` (không commit; mỗi dòng một chuỗi) | file đang track + lịch sử — domain, IP, tên dự án khác, email |
| Key còn sống | **trufflehog** `--results=verified,unknown` (tuỳ chọn) | lịch sử git; key tìm thấy được gửi tới đúng nhà cung cấp để kiểm |

**Bảng mặc định (R11)** — thiếu công cụ / cấu hình thì in cảnh báo kèm `DEFAULTS_APPLIED`:

| Thiếu | Hành vi | Nguồn thật |
|---|---|---|
| `gitleaks` trong PATH | chạy image `ghcr.io/gitleaks/gitleaks:v8.30.1` (`GITLEAKS_VERSION`); không có cả Docker → thoát 2 | binary từ [releases](https://github.com/gitleaks/gitleaks/releases) |
| `.secrets/private-terms.txt` | bỏ bước tên riêng | `PRIVATE_TERMS_FILE` |
| `trufflehog` | bỏ bước key còn sống | binary từ [releases](https://github.com/trufflesecurity/trufflehog/releases) |

- Báo sai → thêm ngoại lệ **hẹp** vào `.gitleaks.toml` (đúng giá trị giả, ghi file + lý do); không bỏ qua cả thư mục.
- Tài liệu chỉ ghi chỗ giữ `<domain>` / `<server-ip>` / `<user>`; giá trị thật của bản deploy ở `.secrets/` (không commit).
- Hook tuỳ chọn trên máy: `printf '#!/bin/sh\nexec make -s secrets-scan\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push`.

## Smoke

| Profile (lệnh) | Cửa web | Ghi dữ liệu | Kiểm cache header | IP thật lấy từ | Lượt Mongo tắt |
|---|---|---|---|---|---|
| **`local`** — `make dev-up MONGO=on\|off` rồi `make smoke-local MONGO=on\|off` | proxy Vite `127.0.0.1:8201` | có — chỉ namespace `bizwithagents_e2e`: user `smoke-*@smoke.test` bị khoá cuối lượt, role `smoke-*`, chuyên gia `smoke_helper`, tổ chức `Smoke *` + admin `owner-*@smoke.test` | ✗ | `X-Forwarded-For` | ✓ (`MONGO=off`) |
| **`prod`** — `make smoke-prod` | domain thật | **không** | ✓ (+ `cf-cache-status`) | Cloudflare ghi đè | theo cấu hình Coolify |

→ Dùng **`local`** mỗi lần sửa backend / frontend, ở cả hai chế độ Mongo; **`prod`** sau mỗi lần push `main` khi Coolify deploy xong (R27) — `make deploy` (dự phòng) tự gọi.

Mỗi profile kiểm:
- **Chung:** bundle + SPA fallback; ready + chế độ Mongo; pipeline; ws health; `public_info`; PWA (manifest + `sw.js`); token sai → `unauthorized` (websocket tới được server).
- **`local` thêm:** đăng nhập / đăng ký superadmin; đăng ký user; rate limit theo IP + email; socket + `core:rbac_updated`; `core:notification`; lỗi có chủ đích (`devtools.raise_error`); event log / issues (hoặc `enabled:false`); `system.status`; agent (gọi tool, override "hỏi duyệt" → duyệt, trace); router (2 bước, hỏi lại, handoff); tenant (tạo tổ chức + mời admin → thư ở outbox console → đăng ký bằng link mời; admin tổ chức mới chỉ thấy user của mình, socket tổ chức khác không nhận `data:changed`); quên mật khẩu qua outbox → đặt lại → token dùng lần hai `2114`; trợ lý theo tổ chức (phiên chat của tổ chức khác → 404 `6004`; tắt trợ lý cho tổ chức → `agent.send` 403 `6023`, `list_agents` rỗng, `auth.me` báo); Tasks (việc tạo ở tổ chức mới → tổ chức khác `tasks.get` 404 `10001`, không thấy trong danh sách, socket không nhận `data:changed`); khoá user → socket bị ngắt. Cần `MAIL_TRANSPORT=console` (mặc định).
- **`prod` thêm:** phiên bản = commit vừa deploy (nếu đặt `SMOKE_EXPECT_VERSION`); không có `/devtools/*`; có `.secrets/smoke.env` thì đăng nhập → me → socket → (superadmin) log + status → đăng xuất.

**Bảng mặc định (R11)** — dòng `smoke: profile=… base=… mongo=… admin=… login=… version=… run=…` in giá trị đang hiệu lực ở đầu mỗi lượt:

| Biến | Mặc định | Nguồn thật |
|---|---|---|
| `SMOKE_EXPECT_MONGO` | bắt buộc ở `local`; `on` ở `prod` | `make smoke-local MONGO=…` |
| `SMOKE_ADMIN_EMAIL` / `SMOKE_ADMIN_PASSWORD` | `local`: `superadmin@test.local` / `SEED_PASSWORD` → `password123` | env |
| `SMOKE_EMAIL` / `SMOKE_PASSWORD` | không đặt → bỏ bước đăng nhập prod | `.secrets/smoke.env` |
| `SMOKE_EXPECT_VERSION` | không đặt → bỏ kiểm phiên bản | `deploy.sh` (= HEAD); tự đặt khi chạy tay sau push |
| `SMOKE_RATE_LIMIT` | khác `1` → bỏ kiểm rate limit trên prod | `.secrets/smoke.env` |
| `SMOKE_RUN_ID` | 6 hex ngẫu nhiên (email / role / IP giả của lượt) | env |

- **`.secrets/smoke.env`** (không commit; chủ dự án tự tạo): nên là tài khoản riêng không có role.
- Script: `realtime/scripts/{smoke_lib,smoke_io,smoke_e2e,smoke_agent,smoke_router,smoke_pwa,smoke_tenant}.ts`, `scripts/dev_stack.sh` + `scripts/stack_env.py`, `scripts/smoke_prod.sh`.

---

*Cập nhật: 2026-10-15*
