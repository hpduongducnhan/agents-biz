# Backend — Logging & correlation id

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [backend/CLAUDE.md](../CLAUDE.md) · [realtime](./realtime.md) · [messaging](./messaging.md) · [observability](./observability.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0: `core/logging.py`, `http_log.py`, `httpx_log.py`, `redact.py`, `http_rules.py`).
- Logger `bw`, bảng tiền tố theo miền ở `LOG_PREFIXES` (`app/core/logging.py`).
- Service realtime Node log **cùng định dạng + cùng cid**.

---

## 1. Một logger

```python
from app.core.logging import get_logger
logger = get_logger(__name__)          # mọi log → logger "bw"; __name__ chỉ để suy ra miền
logger.info("đăng ký user=%s", user.id, extra={"loc": "auth0001"})
```

- **Một logger `bw`** cho mọi process. Không `print`, không tự tạo handler.
- `get_logger` gắn sẵn `module` = miền suy từ tên module (`app.auth.tokens` → `auth`; `app.core…`, `app.main` → `core`).
- `configure_logging(proc, settings)` gọi một lần khi process khởi động; `proc` ∈ `api | consume | work | schedule | migrate`.

## 2. Mã `loc` theo tiền tố miền (R10)

Dạng `<tiền tố><4 chữ số>`.

| Tiền tố | Phân đoạn |
|---|---|
| `boot` | khởi động / tắt process |
| `http` | middleware HTTP vào |
| `hout` | HTTP ra (patch httpx2 / httpx) |
| `bus` | FastStream publish / consume, broadcast |
| `tq` | taskiq |
| `ws` | realtime — Node dải `ws2xxx`, phía Python `ws0xxx` |
| `db` | kết nối Postgres / Mongo / Redis / RabbitMQ |
| `sys` | miền system (nhịp tim, health, cài đặt) |
| `exc` | exception handler HTTP |
| `auth` | auth / RBAC |
| `obs` · `ntf` | quan sát (`obs0001` = Mongo tắt) · thông báo |
| `cred` | credential |
| `agt` | agent |
| `<module>` | module nghiệp vụ tự khai tiền tố ở `LOG_PREFIXES` (vd `tsk` cho Tasks) |

- Cấp mã mới: lấy số cao nhất trong khối của tính năng rồi +1. Kiểm trước:
  `grep -rhoE '"loc": *"<tiền tố>[0-9]+"' backend/app | sort -u`
- Test AST bắt mã sai dạng, sai tiền tố, trùng toàn repo. `warning` / `error` bắt buộc có `loc`.

## 3. Định dạng — `LOG_JSON`

`true` (mặc định ở deploy) → mỗi dòng một object JSON; `false` → text (dev).

```json
{"ts":"2026-10-12T03:00:00.123Z","level":"INFO","logger":"bw","proc":"api","module":"auth",
 "loc":"http0001","cid":"9f2c…","msg":"POST /bizwithagents/api/auth/login 200 34ms",
 "http":{"dir":"in","method":"POST","route":"/bizwithagents/api/auth/login","status":200,"ms":34,"user":"…"}}
```

| Trường | Ý nghĩa |
|---|---|
| `ts` | UTC ISO-8601, mili-giây |
| `level`, `logger`, `proc`, `module`, `loc`, `cid`, `msg` | luôn có (`"-"` khi không có) |
| `http` · `bus` · `task` · `exc` | nhóm cấu trúc theo phân đoạn; `exc` = traceback |
| khác | key trong `extra` |

- Text: `10:00:00.123 INFO  api  cid=9f2c… [http0001] POST /bizwithagents/api/auth/login 200 34ms user=…`
- Lỗi serialize trong formatter → ép giá trị về `str`. Không log ở chỗ này (sẽ đệ quy) — ngoại lệ ghi rõ của B7.

## 4. Correlation id

| Phân đoạn | Nhận cid từ | Truyền đi |
|---|---|---|
| HTTP vào | header `X-Correlation-ID` (≤ 64 ký tự `[A-Za-z0-9_-]`) hoặc sinh mới | header response + `correlation_id` của envelope |
| FastStream `publish` / consume | ContextVar / `message.correlation_id` | property `correlation_id` |
| taskiq `.kiq()` / worker | ContextVar / label `cid` | label `cid` |
| taskiq cron | sinh mới mỗi lần kick | cid đi vào mọi thứ lần chạy tạo ra |
| httpx ra | ContextVar | header chỉ khi rule bật `propagate_cid` |
| Realtime | service Node sinh cid cho event client | AMQP `correlation_id` + trường `cid` của envelope |
| Event log / issues | ContextVar | trường `cid` (tra log ↔ Event log ↔ Issues) |
| Thread | `asyncio.to_thread` (B9) | — |
| Frontend | — | toast lỗi "Mã tra cứu: <cid>" |

## 5. Middleware log HTTP vào

- ASGI thuần — không phá streaming, không làm mất body.
- Một dòng / request (`http0001`): method, route template, path, query (đã che), status, `ms`, user, miền, kích thước.
- Level theo status: 2xx/3xx `INFO` · 4xx `WARNING` · 5xx `ERROR`. Chậm hơn `LOG_HTTP_SLOW_MS` → `WARNING` (`http0002`).
- Body chỉ ghi khi rule `inbound` khớp (§7). Bỏ qua `/health`, `/docs`, `/openapi.json`.

## 6. HTTP ra — patch httpx2 (+ httpx)

- Patch `AsyncClient.send` / `Client.send` một lần lúc khởi động (idempotent).
- Mặc định (`hout0001`) chỉ metadata. Lỗi mạng → `WARNING` `hout0500`, rồi ném lại nguyên vẹn.
- `http_capture(sink)`: raw HTTP cho trace agent — chỉ khi `MONGO_ENABLED=true`.

## 7. Rule theo pattern — `LOG_HTTP_RULES_FILE`

Không có file → chỉ ghi metadata. Rule khớp đầu tiên thắng.

```yaml
http_log:
  max_body: 4096
  inbound:
    - { match: "/bizwithagents/api/tasks/**", req_body: true, resp_body: true }
  outbound:
    - { match: "https://api.anthropic.com/**" }
```

## 8. Che dữ liệu nhạy cảm

1. **Message + args:** `Bearer …`, `sk-…`, `ghp_…`, `api_key=…`, `password=…`.
2. **Header luôn che:** `Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, `Api-Key`, `X-Goog-Api-Key`.
3. **Key JSON** (mọi độ sâu): `password`, `token`, `access_token`, `refresh_token`, `secret`, `api_key`, `authorization`, `credential`; thêm bằng `LOG_REDACT_KEYS`. `input` của event log che theo cùng danh sách.

## 9. Bảng mặc định (R11)

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `LOG_LEVEL` | `INFO` | level logger `bw` |
| `LOG_JSON` | `true` | JSON / text (`.env` dev đặt `false`) |
| `LOG_LIB_LEVEL` | `WARNING` | level thư viện ồn |
| `LOG_HTTP_IN` | `true` | bật middleware HTTP vào |
| `LOG_HTTP_OUT` | `true` | bật dòng log HTTP ra |
| `LOG_HTTP_RULES_FILE` | — | file rule §7 |
| `LOG_HTTP_SLOW_MS` | `1000` | ngưỡng request chậm |
| `LOG_REDACT_KEYS` | — | key cần che thêm |

---

*Cập nhật: 2026-10-12*
