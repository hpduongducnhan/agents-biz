# Backend — Messaging: lane, subscriber / task / cron, broadcast, nhịp tim

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [backend/CLAUDE.md](../CLAUDE.md) · [realtime](./realtime.md) · [operations](./operations.md) · [logging §4](./logging.md) · [decisions](../../platform/design/decisions/README.md)

**Trạng thái:** ĐÃ CHỐT (chép `core/messaging/*` từ dự án nguồn ở SP0). Không có:
- file topology — một RabbitMQ, lane = queue cố định;
- outbox / `@on_event`.

---

## 1. Mặt phẳng

| Mặt phẳng | Công nghệ | Dùng cho | Bền |
|---|---|---|---|
| Việc theo sự kiện | FastStream trên RabbitMQ | `@subscriber` + `publish`; event client `@on_ws` | ✓ queue bền |
| Task / cron | taskiq + `taskiq-aio-pika` | job nền, job định kỳ | ✓ quorum queue |
| Realtime ra | exchange `bw.rt.out` | đẩy sự kiện xuống trình duyệt | ✗ transient |
| Broadcast | exchange `bw.sys.bcast` | báo mọi process xoá cache | ✗ transient |

Một RabbitMQ (`RABBITMQ_URL`, vhost `bizwithagents`); tên sinh từ `app/core/messaging/names.py`.

## 2. API

```python
from app.core.messaging.broadcast import broadcast, on_broadcast
from app.core.messaging.streams import publish, subscriber
from app.core.messaging.tasks import task


@subscriber("system.ping", lane="default")   # queue bw.system.ping
async def on_ping(msg: PingMsg) -> None: ...

await publish("system.ping", msg)              # mang cid


@task("system.ping", lane="default", retry=1, every=15)   # hoặc cron="*/15 * * * *"
async def ping() -> None: ...

await ping.kiq()


@on_broadcast("auth.rbac_changed")
async def drop_cache(data: dict) -> None: ...

await broadcast("auth.rbac_changed", {"user_id": "…"})
```

## 3. Lane (`app/core/messaging/lanes.py` — dict cố định)

| Lane | Queue taskiq | Dùng |
|---|---|---|
| `default` | `bw.tq.default` | mọi việc nền thường (mail, webhook, nhắc hạn…) |
| `agent-run` | `bw.tq.agent-run` | lượt chạy agent |

Queue FastStream `bw.<miền>.<event>`; dead letter task `bw.tq.dead_letter`.

## 4. Process

| Lệnh | Việc |
|---|---|
| `bw api` | HTTP; chỉ publish |
| `bw consume [--lanes …]` | subscriber + `@on_ws` |
| `bw work [--lanes …] [--concurrency N]` | worker taskiq |
| `bw schedule` | cron + `every`; khoá leader Redis `bw:leader:schedule` — deploy chồng lấn thì bản thứ hai chờ |

## 5. Đảm bảo giao

- Ít nhất một lần (FastStream ack sau xử lý; taskiq `when_saved`) → idempotent (B11).
- Handler lỗi → log `bus0500` / `tq0500`, không kẹt queue. `retry=N` → tối đa N+1 lần chạy.
- Process gửi tự khai queue trước khi publish.

## 6. Broadcast `bw.sys.bcast`

- Mỗi process một queue `exclusive` + `auto-delete` bind `#`.
- Chỉ báo "đã đổi"; process tự đọc lại DB.
- Cache xoá theo broadcast phải có TTL (60 giây) để tự lành.

## 7. Nhịp tim pipeline

- Task `system.ping` (`every=HEARTBEAT_INTERVAL`, 15 giây) đi đường thật scheduler → RabbitMQ → worker / consumer.
- Mỗi role ghi `bw:hb:<role>`.
- `GET /bizwithagents/api/health/pipeline`: 200 khi cả ba role có tuổi ≤ 3 × `HEARTBEAT_INTERVAL`; ngược lại 503 kèm `{role: {last, age_s, ok}}`.

---

*Cập nhật: 2026-10-12*
