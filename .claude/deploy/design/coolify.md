# Deploy — Bộ deploy Docker cho Coolify (một compose, chỉ app)

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [deploy/CLAUDE.md](../CLAUDE.md) · [decisions](../../platform/design/decisions/README.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0; mô hình D19 — mạng riêng, migrate trong api, khoá ở env, cổng container 168xx, domain không kèm cổng) — code: `compose.yml`, `deploy/docker/`, `bw keys --print`, `scripts/deploy.sh`, `scripts/smoke_prod.sh`.

---

## 1. Phạm vi

- **Một resource Coolify** (project `bizwithagents`, environment `production`) dựng từ `compose.yml` ở gốc repo, branch `main`.
- **Chỉ app, mạng riêng** (D19). Postgres, MongoDB, Redis, RabbitMQ là instance đã cài trên server (`<server-ip>` — IP LAN), **dùng chung với các app khác** nhưng database / vhost / db index riêng (§4.3) — app nối qua IP host, URL qua env. `deploy/compose.infra.yml` là hạ tầng dự phòng cho máy dev chưa có hạ tầng.
- Mạng: **Cloudflare Tunnel → Traefik của Coolify → service `web`** (§5). Domain `<slug>.<domain>`.

## 2. Service

| Service | Image | Lệnh | Ghi chú |
|---------|-------|------|---------|
| `bw-api` | backend | `sh -c "bw migrate && exec bw api"` | Mỗi lần container khởi động: migration (Alembic, về sau đồng bộ quyền / superadmin / seed — idempotent) rồi mới thành api. Lỗi → container thoát, Docker chạy lại. Healthcheck `/<SERVICE_PATH>/api/health/ready` (Postgres / Redis RW + RO, Mongo theo cờ, RabbitMQ), `start_period` 180 s cho migration |
| `bw-consumer` | backend | `bw consume` | nhận việc từ RabbitMQ; ghi nhịp tim `bw:hb:consume`. Healthcheck (cả worker / scheduler): nhịp tim của role trên Redis mới hơn 90 s (`start_period` 120 s) — Coolify hết báo `running:unknown` |
| `bw-worker` | backend | `bw work` | chạy task (taskiq, mọi lane gồm `agent-run`); ghi nhịp tim `bw:hb:work` |
| `bw-scheduler` | backend | `bw schedule` | cron + nhịp tim — chỉ **1 bản** hiệu lực nhờ khoá leader Redis |
| `bw-realtime` | realtime | `node src/main.ts` | healthcheck `/<SERVICE_PATH>/ws/health`; chỉ cần RabbitMQ + public key |
| `bw-web` | web | nginx | **cửa duy nhất ra ngoài**: bundle FE + proxy API / realtime (§5) |

Thứ tự lên: `bw-api` + `bw-realtime` (không chờ ai) → `bw-consumer` / `bw-worker` / `bw-scheduler` chờ `bw-api` healthy (schema đã ở head) → `bw-web` chờ `bw-api` + `bw-realtime` healthy.

**Tên và mạng:** mọi service mang tiền tố **`bw-`** (`make new-app` đổi theo tiền tố của app). Stack **không** bật Connect To Predefined Network → chỉ ở mạng riêng của resource; Coolify tự nối Traefik vào mạng này nên domain vẫn tới `bw-web`. Domain gắn cho `bw-web` → Coolify sinh `SERVICE_URL_BW_WEB` (gạch ngang thành gạch dưới) — compose dựng `GOOGLE_REDIRECT_URI` + `FRONTEND_AUTH_CALLBACK_URL` từ biến này. Mỗi role **một** container; scale để sau (§8).

`restart: unless-stopped` ở mọi service — lần đầu chạy trên vhost RabbitMQ mới, `bw-consumer` có thể chết một lần vì khai queue quorum `bw.sys.ping` đúng lúc `bw-scheduler` đang tạo nó (`noproc`); Docker khởi động lại là xong.

## 3. Image

Build context = gốc repo; `.dockerignore` loại `.git`, `.claude`, `.env*`, `.secrets`, `design`, `scripts`, `node_modules`, `.venv`, `dist`, `coverage`.

| File | Nội dung |
|------|----------|
| `deploy/docker/backend.Dockerfile` | `python:3.13-slim` 2 stage: Poetry cài dependency `main` vào `.venv` → copy `backend/app`, `backend/migrations` → biên dịch bytecode. Chạy user `bw` (uid 10001). Một image cho mọi role, lệnh đặt ở compose |
| `deploy/docker/realtime.Dockerfile` | `node:26-slim`, `npm ci --omit=dev`, chạy thẳng TypeScript (type stripping), user `node` |
| `deploy/docker/web.Dockerfile` | `node:26-slim` build bundle với build-arg `SERVICE_PATH` (`VITE_API_BASE_URL` / `VITE_WS_PATH` suy ra) → `nginx:alpine` chép sang `scratch` (image chỉ `EXPOSE 16811`) + `deploy/docker/nginx/default.conf.template`. Logo nằm ở `frontend/public/brand/` |

## 4. Cấu hình

### 4.1 Biến môi trường (điền trên Coolify)

| Biến | Bắt buộc | Ghi chú |
|------|----------|---------|
| `POSTGRES_RW_URL` | ✓ | `postgresql+psycopg://<user>:<pw>@<server-ip>:6432/bizwithagents` — qua PgBouncer, kèm `POSTGRES_PGBOUNCER=true` |
| `REDIS_RW_URL` | ✓ | `redis://:<pw>@<host-redis>:6379/<db index riêng>` |
| `RABBITMQ_URL` | ✓ | `amqp://bizwithagents:<pw>@<host-rabbit>:5672/bizwithagents` |
| `SUPERADMIN_EMAILS` | ✓ | danh sách email superadmin, phân tách dấu phẩy — nguồn sự thật của superadmin |
| `AUTH_PRIVATE_KEY` · `AUTH_PUBLIC_KEY` | ✓ | PEM khoá ký JWT — sinh bằng `bw keys --print` (§4.2) |
| `MONGO_ENABLED` | | mặc định `true`; `false` = tắt trace / event log / issues, nghiệp vụ vẫn chạy |
| `MONGO_RW_URL` · `MONGO_DB_NAME` | khi `MONGO_ENABLED=true` | `mongodb://bizwithagents:<pw>@<server-ip>:27017/?authSource=bizwithagents` · `bizwithagents` |
| `SERVICE_URL_BW_WEB` | Coolify tự sinh | URL công khai của `bw-web` theo domain gắn cho service — dựng `GOOGLE_REDIRECT_URI` + `FRONTEND_AUTH_CALLBACK_URL` |
| `SERVICE_PATH` | | mặc định `bizwithagents`; đổi → web build lại |
| `POSTGRES_RO_URL` · `MONGO_RO_URL` · `REDIS_RO_URL` | | replica đọc; trống = dùng RW |
| `POSTGRES_POOL_SIZE` · `POSTGRES_MAX_OVERFLOW` | | compose đặt 3 / 5 mỗi kênh mỗi process (Postgres dùng chung với các app khác) |
| `POSTGRES_PGBOUNCER` | | `true` khi đi qua PgBouncer transaction mode |
| `CREDENTIAL_KEYS` | ✓ (prod) | khoá Fernet mã hoá credential của agent; không tự sinh, phải backup. **Nguồn sự thật = giá trị trong Coolify**; `.secrets/credential_keys.env` = bản sao lưu của giá trị đó (quyền 600) — đổi khoá trên Coolify thì chép lại. Đổi khoá khi đã có credential: thêm khoá mới vào **đầu** danh sách (giữ khoá cũ) → `bw credentials rotate` |
| `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` | | đăng nhập Google — xem *Lựa chọn: scheme* (§6) |
| `PUBLIC_URL` | | URL công khai `https://<slug>.<domain>` — có giá trị thì dựng URL callback Google + frontend từ đây thay `SERVICE_URL_BW_WEB` |
| `REAL_IP_HEADER` | | mặc định `CF-Connecting-IP` |
| `LOG_LEVEL` · `LOG_JSON` · `LOG_REDACT_KEYS` | | mặc định `INFO` · `true` |
| `API_WORKERS` | | số worker uvicorn của `bw-api` (mặc định 1) |

Compose tự đặt: `ENV=prod`, `CORS_ALLOW_ORIGINS=[]` (cùng origin), `FORWARDED_ALLOW_IPS=*`, `BUILD_VERSION=${SOURCE_COMMIT}`, cổng container `16812` (api) / `16813` (realtime) / `16811` (web, `WEB_PORT`) — dải 168xx; Traefik vẫn nghe 80 / 443. Host trong 4 URL DB là **`<server-ip>`** (§4.3).

### 4.2 Khoá ký JWT

- Khoá nằm ở env Coolify, **không** có volume. Sinh một lần trên máy chủ dự án — Claude không chạy lệnh này, để private key không đi qua chat:
  ```bash
  cd backend && poetry run bw keys --print
  # AUTH_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\n…\n-----END PRIVATE KEY-----
  # AUTH_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\n…\n-----END PUBLIC KEY-----
  ```
  Dán nguyên 2 dòng vào Environment Variables. PEM một dòng có `\n` được backend (`Settings`) và realtime (`pemFromEnv`) đưa về nhiều dòng; dán PEM nhiều dòng (ô *Multiline*) cũng được. Coolify có khi lưu thành `\\n` (gạch ngược kép) — cả hai bên đổi mọi `\…\n` thành xuống dòng và bỏ `\` còn sót (PEM không chứa `\`).
- `bw-api` dùng cả hai (ký + kiểm token); `bw-realtime` chỉ nhận `AUTH_PUBLIC_KEY`. Consumer / worker / scheduler nhận chung anchor env nhưng không dùng khoá.
- Thiếu một trong hai → Coolify không cho deploy (`:?`); `bw migrate` cũng dừng (`config_problems`).
- **Xoay khoá:** `bw keys --print` lấy cặp mới → thay cả hai biến → redeploy → mọi người đăng nhập lại.
- Local không đổi: `make migrate` chạy `bw keys` sinh file `.secrets/jwt_*.pem` nếu chưa có.

### 4.3 DB trên server — database / namespace riêng

Dùng chung instance với các app khác; mỗi thành phần một mật khẩu riêng (`openssl rand -hex 24`).

**Postgres chỉ nghe `localhost`:** app đi qua **PgBouncer `<server-ip>:6432`** (`* = host=localhost`, `auth_type = md5`, user của app có trong `userlist.txt` và là thành viên của role chủ DB), kèm `POSTGRES_PGBOUNCER=true`. RabbitMQ user `bizwithagents` — mất mật khẩu thì `rabbitmqctl change_password bizwithagents …` rồi sửa `.secrets/prod.env` + `.env` + Coolify. Giá trị thật của bản deploy (domain, IP, user, tên container) chỉ ghi ở `.secrets/` — không ghi vào tài liệu. Bảng dưới là cách tạo namespace cho lần dựng mới.

| DB | Tạo | Cần |
|----|-----|-----|
| Postgres ≥ 16 | `CREATE ROLE bizwithagents LOGIN PASSWORD '…'; CREATE DATABASE bizwithagents OWNER bizwithagents;` | user **sở hữu database** (migration tạo extension `citext`) |
| MongoDB | `use bizwithagents` · `db.createUser({user: "bizwithagents", pwd: "…", roles: [{role: "readWrite", db: "bizwithagents"}]})` | `readWrite` trên `bizwithagents` |
| Redis | chọn **ba** db index **trống** (dev / prod · test · stack thử — `INFO keyspace`, rồi `-n <db> DBSIZE` → 0) | mọi key có tiền tố `bw:` |
| RabbitMQ | `rabbitmqctl add_vhost bizwithagents` · `add_user bizwithagents '…'` · `set_permissions -p bizwithagents bizwithagents ".*" ".*" ".*"` | quyền `.*` trên vhost (app tự khai exchange / queue `bw.*`) |

**Host = `<server-ip>`** + cổng mà instance nghe trên LAN (thường 5432 / 27017 / 6379 / 5672), **không** dùng hostname nội bộ trên mạng `coolify` — stack BizWithAgents không ở mạng đó. Kiểm trước từ một máy trong LAN: `nc -zv <server-ip> <cổng>` cho từng DB. Không mở được → DB chưa publish cổng ra host (resource Coolify: bật *Make it publicly available*) hoặc firewall chặn.

## 5. Mạng: một cửa `web`

```
Trình duyệt ─HTTPS→ Cloudflare ─Tunnel→ Traefik (Coolify, <server-ip>:80) ─→ bw-web:16811 (nginx)
                                                                              ├─ /                    → bundle FE (SPA fallback)
                                                                              ├─ /bizwithagents/api/       → bw-api:16812
                                                                              └─ /bizwithagents/ws/        → bw-realtime:16813 (WebSocket)
bw-api / consumer / worker / scheduler / realtime ─→ <server-ip>:<cổng> (Postgres · Mongo · Redis · RabbitMQ dùng chung)
```

- Chỉ `bw-web` có domain; api / realtime / backend không mở cổng. Cùng origin → không CORS.
- Mạng riêng của stack: tên `bw-api` / `bw-realtime` chỉ phân giải trong stack này. Kiểm sau deploy: `docker exec <container bw-web> nslookup bw-api 127.0.0.11` → một IP.
- **Điểm vào của tunnel:** `cloudflared` chạy trong container riêng → origin của public hostname là **IP LAN của server** (`http://<server-ip>:80`), **không** phải `localhost:80`. Tunnel giữ nguyên header `Host` nên Traefik định tuyến đúng.
- **IP thật:** nginx lấy IP từ `REAL_IP_HEADER` (`CF-Connecting-IP`), gửi `X-Forwarded-For` / `X-Real-IP`; uvicorn tin header đó (`FORWARDED_ALLOW_IPS=*`, an toàn vì api chỉ nhận từ web) → rate limit đăng nhập và log `http.ip` đúng người dùng.
- nginx phân giải lại `bw-api` / `bw-realtime` qua DNS Docker mỗi 10 s → container tạo lại không làm web trả 502.
- Cache: `/assets/*` `immutable` 1 năm; `index.html` `no-cache` → bản mới hiện ngay.
- Giới hạn: `/api/` `proxy_read_timeout 120s` (Cloudflare cắt 524 sau 100 s không có byte); `client_max_body_size 2m`; WebSocket `proxy_read_timeout 1h`.

## 6. Runbook Coolify

1. **Repo:** GitHub private `<owner>/<slug>` (branch `main`); GitHub App của Coolify (dùng chung cho mọi app trên Coolify này) được cấp quyền repo. Webhook của GitHub App phải trỏ `https://coolify.<domain>/webhooks/source/github/events` (event `push`) — trỏ sai domain thì GitHub giao lỗi 502 và push không tự deploy (R27). Kiểm ở GitHub App → Advanced → Recent Deliveries.
2. **Resource mới** trong project `<slug>` → Application → *Private Repository (with GitHub App)* → repo của app, branch `main`.
3. **Build Pack** = Docker Compose · **Base Directory** `/` · **Docker Compose Location** `/compose.yml`.
4. **Domain:** chỉ service `bw-web` → `http://<slug>.<domain>`, **không** kèm cổng: image web chỉ khai `EXPOSE 16811` và compose `expose: ["16811"]` → Coolify ghi label cổng cho Traefik. Service khác để trống (đặc biệt `bw-api`).
5. **Environment Variables:** bảng §4.1 (6 biến bắt buộc + `MONGO_*`; host DB `<server-ip>` — §4.3; khoá từ `bw keys --print` — §4.2). Bộ đầy đủ ở `.secrets/prod.env` → dán vào **Developer view**. Coolify tự tạo mọi key `${VAR:?}` của compose với giá trị **rỗng** nên compose không chặn — biến bắt buộc nào rỗng thì `bw-api` dừng ở `bw migrate` (`boot0501 … chưa cấu hình`), realtime thoát ngay. Kiểm `SERVICE_URL_BW_WEB` = `http://<slug>.<domain>` (không kèm cổng — dựng `GOOGLE_REDIRECT_URI` / `FRONTEND_AUTH_CALLBACK_URL`).
6. **Settings:** **tắt** Connect To Predefined Network, bật **Include Source Commit in Build** (Coolify mới truyền `SOURCE_COMMIT` → `BUILD_VERSION` → `/health/live` báo đúng commit; tắt thì báo `dev` và `make deploy` không chứng minh được bản mới). Ghi lại **application uuid** (trên URL trang app) vào `.secrets/coolify.env` (§6.1).
7. **Cloudflare Tunnel:** public hostname `<slug>.<domain>` → `http://<server-ip>:80` (§5).
8. **Deploy** → thứ tự lên: `bw-api` (migration rồi api) + `bw-realtime` healthy → `bw-consumer`, `bw-worker`, `bw-scheduler` → `bw-web` healthy. Log từng service ở tab Logs (JSON, có `loc`, `cid`); log migration nằm ở đầu log `bw-api`.
9. **Kiểm:** `make smoke-prod URL=https://<slug>.<domain>` → 4 dòng `✓`; mở trang thấy logo + 5 đèn xanh.

### 6.1 `make deploy`

`.secrets/coolify.env` (không commit — `.gitignore` có `.secrets/`):

```dotenv
COOLIFY_URL=https://coolify.<domain>
COOLIFY_TOKEN=<token API Coolify, quyền deploy + read>
COOLIFY_APP_UUID=<application uuid — §6 bước 6>
PUBLIC_URL=https://<slug>.<domain>
```

`scripts/deploy.sh` (`make deploy`):
1. Từ chối khi còn thay đổi chưa commit, hoặc `HEAD` khác `origin/main` (deploy đúng thứ đã push).
2. `POST /api/v1/deploy {uuid}` (Bearer token).
3. Chờ `GET /api/v1/deployments/<id>` tới `finished` (tối đa `DEPLOY_POLLS` × `DEPLOY_POLL_SEC` = 90 × 10 s). `failed` / `cancelled*` **hoặc hết giờ** → thoát lỗi, không smoke bản cũ.
4. `EXPECT_VERSION=<commit vừa push> scripts/smoke_prod.sh $PUBLIC_URL`: web (`id="root"`), **phiên bản** (`/health/live` `data.version` = commit — chờ tới khi container mới lên), `api/health/ready`, `api/health/pipeline` (nhịp tim), `ws/health` — mỗi mục thử lại tới ~2,5 phút (`SMOKE_TRIES` × `SMOKE_SLEEP`). Không ghi dữ liệu. `make smoke-prod URL=…` không đặt `EXPECT_VERSION` thì bỏ mục phiên bản.

Test: `backend/tests/deploy/test_scripts.py` chạy hai script với server HTTP giả (Coolify + domain) và repo git tạm.


### 6.2 Dạng JSON của API Coolify

`deploy.sh` đọc `deployments[0].deployment_uuid` của `POST /api/v1/deploy` và `status` của `GET /api/v1/deployments/<id>`. Đã kiểm trên Coolify thật (dự án nguồn); khác tên trường thì sửa hai dòng `python3 -c` trong script và ghi dạng đúng vào đây.

### Lựa chọn: scheme của domain trong ô Domains của Coolify

Scheme ở ô Domains điều khiển hai thứ không liên quan nhau:

| | |
|---|---|
| **Label Traefik** | `https://` sinh thêm router `https` kèm `tls.certresolver=letsencrypt`; middleware `redirect-to-https` chỉ gắn vào router `http` khi "Force HTTPS" bật |
| **`SERVICE_URL_BW_WEB`** | Coolify ghi đè biến này bằng scheme của domain **đầu tiên**, mỗi lần deploy → dựng `GOOGLE_REDIRECT_URI` + `FRONTEND_AUTH_CALLBACK_URL` |

| Phương án | Origin | Cert Let's Encrypt | Lặp redirect | Đăng nhập Google |
|---|---|---|---|---|
| **`http://`** | HTTP | ✗ (không cần) | ✗ | ✗ (Google từ chối redirect `http://`) |
| `https://` + tắt Force HTTPS | HTTP | xin qua tunnel (thừa) | ✗ | ✓ |
| `https://` + bật Force HTTPS | — | — | ✓ (hỏng) | — |

→ Chọn **`http://`** vì HTTPS kết thúc ở Cloudflare; đăng nhập Google dùng `PUBLIC_URL` (bên dưới) nên không cần đổi scheme.
- **Đã cân nhắc:** `https://` + tắt Force HTTPS — **đổi sang khi bật Google OAuth**; `https://` + bật Force HTTPS — lặp redirect qua tunnel.

**Bật đăng nhập Google:**
1. Chủ dự án: OAuth client (Web) — origin `https://<slug>.<domain>`, redirect `https://<slug>.<domain>/bizwithagents/api/auth/google/callback`; dán `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` vào Coolify.
2. ~~Đổi domain sang `https://` + tắt Force HTTPS~~ → **thay bằng env `PUBLIC_URL=https://<slug>.<domain>`**: app dựng `GOOGLE_REDIRECT_URI` = `https://…/bizwithagents/api/auth/google/callback` và `FRONTEND_AUTH_CALLBACK_URL` = `https://…/auth/callback` từ biến này; domain Coolify giữ `http://`, Force HTTPS không ảnh hưởng (router `http` không có redirect khi domain là `http://`). Redeploy để nhận env.
3. `make smoke-prod`; superadmin bật "Đăng nhập Google" ở `/sa/settings` (chỉ bật được khi đủ env — `google_configured`).

**Cập nhật bản chạy (R27):** commit + push `main` → Coolify tự deploy qua webhook GitHub App → theo dõi deployment tới `finished` → `make smoke-prod URL=https://<slug>.<domain>`. `make deploy` chỉ khi webhook không chạy. Migration chạy lại ở đầu `bw-api` mỗi lần container khởi động.
**Quay lại bản cũ:** redeploy commit cũ trong Deployments của Coolify — migration không tự downgrade.

## 7. Kiểm chứng

| Lệnh | Kiểm |
|------|------|
| `make be-test` · `cd backend && poetry run pytest tests/deploy -q` | cấu trúc `compose.yml`: 6 service `bw-*`, không publish cổng, không volume / mạng ngoài, env bắt buộc `:?` (cả khoá JWT), Mongo tuỳ cờ, thứ tự healthcheck, `bw-web` là cửa duy nhất, upstream mặc định của image web khớp compose |
| `make smoke-prod URL=…` | 4 mục qua domain thật, không ghi dữ liệu |
| `make deploy` | deploy + chờ + smoke |
| Unit test | `bw keys` (sinh / giữ / env thắng / cấu hình nửa vời), `bw keys --print` → env một dòng đọc lại được qua `Settings`, `bw migrate` chạy lại không lỗi |

- Sau mỗi lần push `main` (Coolify tự deploy — R27): `make smoke-prod` = 4 kiểm cơ bản rồi smoke đầu-cuối profile `prod` (không ghi dữ liệu) — [deploy, mục Smoke](../CLAUDE.md).
- **Phiên bản đang chạy:** compose đặt `BUILD_VERSION=${SOURCE_COMMIT:-dev}`; bật **Include Source Commit in Build** → `curl -s https://<slug>.<domain>/bizwithagents/api/health/live` trả `version` là SHA.
- **Cloudflare:** không đặt quy tắc cache cho HTML (`index.html` phải `cf-cache-status` khác `HIT`); WebSockets bật (tab Network).
- **`ENV`** trên Coolify phải là `prod` (mặc định của compose) — smoke prod kiểm `/devtools/*` → 404.

## 8. Để sau

- **Scale:** replica > 1, tách consumer / worker theo lane. `bw-api` > 1 bản → bọc migration bằng `pg_advisory_lock` để các bản không chạy Alembic cùng lúc.
- Instance realtime khởi động **sau** lệnh khoá tài khoản (`rt:revoke`) không biết lệnh đó — socket của user bị khoá nối vào instance ấy vẫn nhận tới khi token hết hạn.
- Giới hạn CPU / RAM từng service.

---

*Cập nhật: 2026-10-15*
