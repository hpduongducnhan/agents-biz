# Backend — Kết nối Postgres / Mongo / Redis: 2 kênh RW + RO, theo process role, cờ `MONGO_ENABLED`

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [backend/CLAUDE.md](../CLAUDE.md) · [logging](./logging.md) · [observability](./observability.md) · [operations](./operations.md) · [decisions](../../platform/design/decisions/README.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0). RabbitMQ: [messaging](./messaging.md). Hạ tầng dùng chung trên server theo D19.

---

## 1. Mỗi tài nguyên có 2 kênh

| Tài nguyên | RW (ghi + đọc-ngay-sau-ghi) | RO (đọc chịu được hơi cũ) |
|---|---|---|
| Postgres | `POSTGRES_RW_URL` | `POSTGRES_RO_URL` |
| Mongo (chỉ log, theo cờ) | `MONGO_RW_URL` (+ `MONGO_DB_NAME`) | `MONGO_RO_URL` |
| Redis | `REDIS_RW_URL` | `REDIS_RO_URL` |

- Chỉ cấu hình RW → RO copy nguyên connection string (vẫn pool / client riêng). Code đi đúng đường RO ngay từ dev; lên replica chỉ cần thêm biến.
- `Settings.postgres_ro_url` / `mongo_ro_url` / `redis_ro_url` = `*_RO_URL or *_RW_URL` — một chỗ quyết định fallback.

## 2. Kênh RO thật sự read-only

- **Postgres:** session RO mở transaction `READ ONLY` → ghi nhầm kênh là lỗi ngay.
- **Mongo:** handle RO dùng `readPreference=secondaryPreferred`.
- **Redis:** client RO chỉ dùng cho lệnh đọc.

## 3. Dùng đúng kênh

| Việc | Kênh |
|---|---|
| `@operation` `effect="read"` | RO (mặc định) |
| `effect="write"` / `"destructive"` | RW |
| Đọc lại thứ vừa ghi trong cùng luồng | RW (`read_from="rw"` + lý do) |
| Danh sách / báo cáo | RO |
| Kiểm quyền trước khi ghi | RW nếu quyết định ghi dựa vào nó |
| Redis: đọc cache | RO |
| Redis: ghi / khoá / rate limit / dấu khoá tài khoản | RW |
| Thông báo (inbox) | RW (session ngắn sau commit) |

## 4. Kết nối theo process role — tạo một lần, nhận qua inject

- `init_connections(role, settings)` (`app/core/connections/registry.py`) chạy trong lifespan của mỗi process.
  - Tạo đúng thứ role cần, rồi ping **mọi kênh**.
  - Lỗi → đóng hết và không boot (`db0501`).
- `get_connections()` / `close_connections()`.

| Role (`bw …`) | Cần |
|---|---|
| `api`, `consume`, `work` | Postgres + Redis + Mongo (khi cờ bật) |
| `schedule` | Postgres + Redis |
| `migrate` | Postgres |

- Trong `@operation`: `ctx.session` (Postgres đúng kênh), `ctx.redis` (`.rw` / `.ro`), `ctx.mongo` (`None` khi tắt cờ). Ngoài operation: `get_connections()`.
- Không miền nào tự tạo engine / client (`create_async_engine`, `AsyncMongoClient`, `redis.asyncio.from_url`, `psycopg.connect`…).

## 5. Chế độ `MONGO_ENABLED`

| `MONGO_ENABLED` | Client Mongo | `/health/ready` | Event log / issues / trace | API đọc log | Cảnh báo |
|---|---|---|---|---|---|
| **`true`** (mặc định) | ✓ — ping lúc boot | `mongo.rw` / `mongo.ro` = `ok` | ghi qua sink Mongo | dữ liệu thật | — |
| `false` | ✗ | `"mongo": "disabled"` (vẫn 200) | sink Noop | `{enabled: false, items: [], total: 0}` | `obs0001` một lần mỗi process |

→ Dùng **`true`** khi có Mongo. `false` khi không có / không muốn tốn Mongo: nghiệp vụ + chat vẫn chạy, chỉ tắt log.
- **Đã cân nhắc:** bảng `audit_log` ở Postgres — chỉ cần dấu vết tối thiểu (`created_by`, `source`, `agent_run_id` ở Postgres).

Kiểm thật:
- `make dev-up MONGO=off` đặt `MONGO_RW_URL` trỏ host `.invalid`;
- `make smoke-local MONGO=off` và `make docker-smoke` (lượt `smoke-nomongo.env`) chạy đầu-cuối ở chế độ này.

## 6. Postgres — một driver

Mọi kênh dùng `postgresql+psycopg://`. Thư viện cần psycopg thô (checkpointer LangGraph, schema `agent_lg`) lấy pool thô do lõi giữ.

**Qua PgBouncer (prod, `POSTGRES_PGBOUNCER=true`):** `prepare_threshold=None` (không prepared statement). Tham số khởi động `options` được PgBouncer chấp nhận nhưng **chỉ `search_path` có hiệu lực** (đo 2026-10-12: `-c search_path=agent_lg` → đúng schema; `-c statement_timeout=30000` → `0`). Hệ quả:
- checkpointer `agent_lg` chạy đúng qua PgBouncer (đã thử setup / ghi / đọc / xoá thread trên `bizwithagents_e2e:6432`);
- `POSTGRES_STATEMENT_TIMEOUT` **không áp** khi đi PgBouncer — truy vấn treo không bị cắt ở phía DB.

| Cách áp `statement_timeout` qua PgBouncer | Ai làm | Round-trip thêm | Đụng hạ tầng chung |
|---|---|---|---|
| **Thêm `statement_timeout` vào `track_extra_parameters` của PgBouncer** | chủ dự án | 0 | ✓ (file cấu hình PgBouncer dùng chung với các app khác — chỉ có tác dụng với client gửi tham số) |
| `SET LOCAL statement_timeout` ở sự kiện `begin` của engine | Claude | +1 mỗi transaction | ✗ |
| Để nguyên (timeout ở client: `asyncio.timeout` của lượt agent, timeout HTTP) | — | 0 | ✗ |

→ Đề xuất cách 1 (rẻ nhất, không đổi code); đã báo chủ dự án. Chưa làm thì giữ cách 3.

## 7. Bảng mặc định (R11)

| Key | Mặc định | Nguồn thật khi được cấu hình |
|---|---|---|
| `POSTGRES_RO_URL` | = `POSTGRES_RW_URL` | env |
| `MONGO_RO_URL` | = `MONGO_RW_URL` | env |
| `REDIS_RO_URL` | = `REDIS_RW_URL` | env |
| `POSTGRES_RO_POOL_SIZE` | = `POSTGRES_POOL_SIZE` (10) | env |
| `MONGO_ENABLED` | `true` | env (Coolify / `.env`) |
| `MONGO_DB_NAME` | `bizwithagents` | env |
| `REDIS_RW_URL` (local) | `redis://127.0.0.1:6379/10` | `.env`; test dùng db 11, stack thử db 12 (D19) |
| `POSTGRES_STATEMENT_TIMEOUT` | 30 s — áp khi nối thẳng Postgres; **qua PgBouncer không áp** (§6) | env |

---

*Cập nhật: 2026-10-12*
