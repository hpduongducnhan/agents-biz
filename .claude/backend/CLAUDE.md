# CLAUDE.md — Backend

> **Backlinks:** [CLAUDE.md](../../CLAUDE.md) | platform/CLAUDE.md · [template-v1](../platform/design/template-v1.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0). Rule chung ở [CLAUDE.md](../../CLAUDE.md) (R1–R28) — file này **không chép lại**, chỉ ghi chi tiết riêng của backend.

Backend **Python 3.13** ở `backend/`, CLI `bw`. Thư viện:
- FastAPI + FastStream + taskiq trên **RabbitMQ**;
- SQLModel / SQLAlchemy + psycopg3 (**Postgres**);
- **Redis** (cache / KV), Alembic một chuỗi, httpx2.

**Mongo** chỉ để ghi log, tắt được bằng `MONGO_ENABLED`. Realtime tới trình duyệt đi qua service Node `realtime/` — backend chỉ publish vào RabbitMQ.

## Menu tài liệu

| File | Trạng thái | Nội dung |
|------|-----------|----------|
| [connections](./architecture/connections.md) | ĐÃ CHỐT | Postgres / Mongo / Redis: 2 kênh RW + RO, kết nối theo process role, chế độ `MONGO_ENABLED`, bảng mặc định |
| [logging](./architecture/logging.md) | ĐÃ CHỐT | Logger `bw`, mã `loc` theo tiền tố miền, JSON / text, cid xuyên HTTP → AMQP → taskiq → realtime, log HTTP vào / ra, che dữ liệu |
| [messaging](./architecture/messaging.md) | ĐÃ CHỐT | Lane cố định, `@subscriber` / `publish`, `@task` + cron + khoá leader, broadcast xoá cache, nhịp tim pipeline |
| [operations](./architecture/operations.md) | ĐÃ CHỐT | `@operation` → REST (quy ước đường dẫn) + action cho agent; runner, `OpContext`, việc sau commit, `ui_only`, công cụ dev |
| [realtime](./architecture/realtime.md) | ĐÃ CHỐT | Chiều ra `bw.rt.out` (user / sup / all), chiều vào `@on_ws`, envelope, event lõi, khoá tài khoản → `rt:revoke` |
| [observability](./architecture/observability.md) | ĐÃ CHỐT | Sink event log / issues (Mongo hoặc Noop), API đọc log `enabled:false`, thông báo (inbox), cài đặt hệ thống + bảng mặc định |

Auth / RBAC (cross-stack): [platform/auth-rbac](../platform/architecture/auth-rbac.md). Trợ lý: [agent-runtime](../platform/architecture/agent-runtime.md). Deploy, môi trường local, smoke: [deploy](../deploy/CLAUDE.md).

---

## Rule gốc áp cho backend — chi tiết riêng

| Rule gốc ([CLAUDE.md](../../CLAUDE.md)) | Ở backend BizWithAgents |
|---|---|
| R6 envelope | `ApiResponse` ở `app/core/response.py`; lỗi nghiệp vụ `AppException(code, status_code)`; mỗi miền `register_errors({...}, owner="<miền>")` trong dải (`ERROR_RANGES`, `app/core/errors.py`): 1xxx core · 2xxx auth / RBAC (+ tenant từ SP1) · 6xxx agent · 7xxx quan sát + thông báo · 8xxx mail (SP1); module nghiệp vụ dùng dải 5 chữ số `1NNxx` |
| R7 OpenAPI | `make openapi` (= `bw dump-openapi`) sau mỗi lần thêm / sửa `@operation`, commit `frontend/src/lib/api/openapi.json`; `make openapi-check` trong `make ci`; route `/devtools/*` không vào hợp đồng ([operations §7](./architecture/operations.md)) |
| R8 import đầu file | áp cả `tests/` và `scripts/`; ngoại lệ ghi `# defer: tránh vòng import với <X>` |
| R9 ≤ ~400 dòng (test / kịch bản kiểm ≤ ~800) | miền lớn → `app/<miền>/<tính-năng>/{ops,service,models}.py` |
| R10 mã `loc` | bảng tiền tố ở [logging §2](./architecture/logging.md) |
| R11 mặc định quan sát được | bảng mặc định ở [connections §7](./architecture/connections.md) và [observability §6](./architecture/observability.md) |
| R12 cờ → một choke-point | Mongo: `get_sinks()` ([observability §1](./architecture/observability.md)) — gồm `traces` (`TraceSink`); công cụ dev: `devtools_enabled()` |
| R13 discriminated union | document event log; span trace `agent/trace/spans.py` + hành động hook `agent/hooks/schemas.py`; action + params thông báo theo `register_kind` |
| R14 phân trang | `PageIn` / `Page` ở `app/core/operations/pagination.py` |
| R18 realtime-first | `invalidates` + `ctx.invalidate(..., users=…)`, gửi sau commit ([realtime](./architecture/realtime.md)) |

## Rule riêng của backend (root chưa có)

### B1 — Layering một chiều
Luồng đi một chiều: **adapter → handler → core**.
- **Adapter:** REST sinh từ `@operation`, route tay `ui_only` (Google OAuth redirect), action cho agent. Adapter chỉ lo shape request / response: không logic, không query DB.
- **Handler:** hàm `@operation`.
- **`app/core/`** không import ngược lên miền nghiệp vụ.

### B2 — Postgres chỉ một driver `psycopg3`
DSN `postgresql+psycopg://…`. Cấm `asyncpg`.

### B3 — Việc bất đồng bộ đi qua RabbitMQ, không gọi HTTP nội bộ
- Dùng `@subscriber` + `publish` hoặc `@task` + `.kiq()`.
- Tên queue / exchange sinh từ `app/core/messaging/names.py` (`bw.*`); lane khai ở `lanes.py`.

### B4 — Consumer tách khỏi logic
`@subscriber` / `@task` / `@on_ws` chỉ là wiring; logic ở hàm thường, test được không cần broker.

### B5 — Migration một chuỗi Alembic
- Đổi schema: `bw revision -m "<mô tả>"` → `migrations/versions/00NN_<mô tả>.py`; kiểm `down_revision` → `make migrate`.
- Không `create_all` ngoài test. Model mới import trong `app/models/__init__.py`.

### B6 — Đúng kênh RW / RO
- `effect="read"` → session RO (`READ ONLY`); ghi / đọc-ngay-sau-ghi → RW (`read_from="rw"` + lý do).
- Redis đọc qua `.ro`, ghi qua `.rw`.

### B7 — Nuốt exception thì phải log
`except Exception` không ném lại → bắt buộc có cả hai:
- `logger.warning("<việc gì hỏng>: %s", exc, extra={"loc": "…"})`;
- `# noqa: BLE001 — <lý do>`.

Test luật bắt chỗ thiếu. Nuốt lỗi im lặng làm tính năng chết trong khi test vẫn xanh.

### B8 — Gọi HTTP ra ngoài chỉ bằng httpx2
Bản vá log HTTP ra chỉ bắt `httpx2` / `httpx`. Cấm `requests`, `aiohttp`, `urllib`.

### B9 — Chạy ở thread thì giữ context
`asyncio.to_thread(...)`. Không `run_in_executor` trần.

### B10 — RabbitMQ lo message, Redis chỉ cache / KV
- Cấm Redis pub/sub / list làm queue.
- Mọi key qua `rkey(...)` → tiền tố `bw:` (Redis dùng chung instance).

### B11 — Task và consumer idempotent
Broker giao ít nhất một lần → chạy lại cùng message không gây tác dụng kép.

### B12 — Test không đụng dữ liệu thật
- Postgres `bizwithagents_test` (xoá schema chỉ khi tên kết thúc `_test`), Mongo `bizwithagents_test`, Redis db **11** (D19), vhost `bizwithagents_test`, khoá JWT sinh tạm.
- Marker `integration` cho test cần hạ tầng.
- `make be-cov` ≥ 90% dòng `app/`.

### B13 — Công cụ dev không bao giờ lên prod
- `app/devtools/` chỉ nạp khi `ENV ∈ {dev, smoke}`; route bị gỡ khi ENV khác và không bao giờ vào OpenAPI.
- Không thêm thao tác nghiệp vụ vào đây.
- Kiểm: `tests/test_smoke_contract.py` + smoke prod (`/devtools/*` → 404).

### B14 — Dữ liệu khách hàng tách theo tenant
- Bảng nghiệp vụ của module kế thừa `TenantScoped` (`app/core/tenancy.py`) — lõi tự lọc / tự gán `tenant_id` (D10–D11, [tenancy](../platform/architecture/tenancy.md)).
- Bảng toàn nền tảng (không `tenant_id`) phải có tên + lý do trong `PLATFORM` của test luật; bảng module nghiệp vụ thì không.
- Không SQL thô (`text()`) / bảng Core (`Model.__table__`) trên bảng `TenantScoped` — bộ lọc chỉ chạy trên câu ORM. Cần đọc xuyên tenant → `ctx.cross_tenant()` (chỉ superadmin) hoặc `execution_options(all_tenants=True)` có lý do.
- Kiểm: `tests/rules/test_rule_b14.py`.

---

*Cập nhật: 2026-10-15*
