# Backend — Quan sát (event log, issues), thông báo, cài đặt hệ thống

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [backend/CLAUDE.md](../CLAUDE.md) · [connections §5](./connections.md) · [operations](./operations.md) · [realtime](./realtime.md) · [decisions](../../platform/design/decisions/README.md)

**Trạng thái:** ĐÃ CHỐT.
- Chép từ dự án nguồn ở SP0: interface + bản Noop, sink Mongo, thông báo, cài đặt hệ thống.
- Dấu vết thao tác là `event_log` trong Mongo (theo cờ).

---

## 1. Sink — một choke-point ghi log (R12)

- `get_sinks() -> Sinks(event_log, issues, enabled)`.
- `init_observability(settings, mongo)` — mọi role gọi lúc boot. Hai chế độ theo `MONGO_ENABLED` ([connections §5](./connections.md)):
  - `true` → sink Mongo, ghi nền qua hàng đợi giới hạn 1000 mục. Đầy thì bỏ + log; không làm hỏng request.
  - `false` → Noop + `obs0001` một lần mỗi process, sau đó chỉ debug.
- Không miền nào ghi Mongo trực tiếp.

## 2. Event log (`event_log`)

Mỗi `@operation` có `effect != read` → một document (thành công hoặc lỗi):

```
{ts, cid, actor_id, actor_sup, source, agent_run_id, operation, effect, owner, input (đã redact), ok, error_code,
 duration_ms, expire_at}
```

- TTL: index `expireAfterSeconds=0` trên `expire_at = ts + event_log_ttl_days`.
- Thêm sự kiện đăng nhập / đăng xuất / khoá tài khoản.

## 3. Issues (`issues`, không TTL)

- **Nguồn:** exception chưa bắt ở HTTP (5xx), lỗi task taskiq / consumer FastStream. Agent thêm run lỗi hệ thống, key bị tắt.
- `AppException` < 500 không phải issue.
- `fingerprint = sha1(loại exception + frame đầu tiên thuộc app + loc)`; upsert `count`, `last_seen`, `recent` (20 cid), `sample` (traceback đã che ≤ 20KB).
- Trạng thái `open | resolved | ignored`; `resolved` gặp lại → mở lại.
- Issue mới → thông báo `issue_new` cho superadmin, tối đa 1 lần / fingerprint / giờ (khoá Redis `bw:obs:issue_notified:<fp>`).
- Gây lỗi thử ở dev: `devtools.raise_error` ([operations §7](./operations.md)).

## 4. API đọc log (superadmin)

| REST | Việc |
|---|---|
| `GET /notifications/list` | Danh sách thông báo |
| `POST /notifications/mark_all_read` | Đọc hết |
| `POST /notifications/mark_read` | Đánh dấu đã đọc |
| `POST /notifications/send_test` | Gửi thông báo thử |
| `GET /notifications/unread_count` | Số thông báo chưa đọc |
| `GET /observability/get_issue` | Chi tiết issue |
| `GET /observability/list_events` | Event log |
| `GET /observability/list_issues` | Issues |
| `POST /observability/set_issue_status` | Đổi trạng thái issue |
| `GET /system/get_settings` | Cài đặt hệ thống |
| `GET /system/public_info` | Thông tin công khai |
| `GET /system/status` | Trạng thái hệ thống |
| `POST /system/update_settings` | Sửa cài đặt hệ thống |

- Tắt Mongo → **200** `{enabled: false, items: [], total: 0}`; UI hiện banner "Ghi log đang tắt (MONGO_ENABLED=false)".
- Mongo chết khi cờ bật → 503 mã `7001` (không treo request).

## 5. Thông báo (inbox — Postgres `notifications`)

- `ctx.notify(user_id, kind, title, body, params, action)` → sau commit, notifier ghi dòng (session RW ngắn) rồi đẩy `core:notification`. Người nhận offline vẫn có trong inbox.
- Kind nền: `issue_new` (superadmin), thông báo thử của `notifications.send_test`, `agent_key_disabled`, `agent_chat_blocked` / `agent_chat_unblocked`, `agent_hook`. Module đăng ký kind của mình bằng `register_kind`.
- Dọn sau 90 ngày (task `notifications.cleanup` của scheduler).
- Op `notifications.*` chỉ đụng dữ liệu của chính người gọi, trừ `send_test`.

## 6. Cài đặt hệ thống — bảng mặc định (R11)

Postgres `system_settings`, một dòng `id=1`, cột `data jsonb`. Đọc qua cache Redis `bw:sys:settings` (TTL 60 giây). Sửa → broadcast `system.settings_changed` xoá cache ở mọi process.

| Khoá | Mặc định | Nguồn thật khi được cấu hình |
|---|---|---|
| `signup_open` | `true` | superadmin ở `/sa/settings` |
| `google_enabled` | `false` (chỉ có hiệu lực khi có `GOOGLE_CLIENT_ID`) | `/sa/settings` |
| `event_log_ttl_days` | `180` | `/sa/settings` |
| `span_ttl_days` | `90` | `/sa/settings` |
| `raw_http_ttl_days` | `7` | `/sa/settings` |

- `system.public_info` (công khai): tên app, `signup_open`, `google_enabled`, `version` — cho trang đăng nhập.
- `system.status` (superadmin): kết nối, nhịp tim, phiên bản, sink quan sát, số issue đang mở — trang `/sa/status` hiện bằng `JsonView` (R17).

## 7. Kiểm chứng

- Test quan sát chạy cả `MONGO_ENABLED=true` lẫn `false`.
- Smoke ([deploy, mục Smoke](../../deploy/CLAUDE.md)):
  - Mongo bật → event log có `rbac.create_role` / `admin.update_user` của lượt; issues có `DevError`;
  - Mongo tắt → `{enabled: false, items: []}`.
- E2E: F5 (event log + `JsonView`), F6 (issue + cid), F7 (thông báo tức thì), F9 (banner).

---

*Cập nhật: 2026-10-12*
