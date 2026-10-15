# Backend — Realtime: RabbitMQ ↔ service Node ↔ trình duyệt

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [backend/CLAUDE.md](../CLAUDE.md) · [messaging](./messaging.md) · [operations](./operations.md) · [observability §5](./observability.md) · [platform/auth-rbac](../../platform/architecture/auth-rbac.md) · [decisions](../../platform/design/decisions/README.md)

**Trạng thái:** ĐÃ CHỐT.
- Chép nguyên từ dự án nguồn ở SP0 (service `realtime/` + phía backend).
- SP1 thêm phòng `tenant:<tid>` (D13).

---

## 1. Đường đi

| Chiều | Đường |
|---|---|
| Ra | `emit_*` → `bw.rt.out` (topic, transient) → instance `realtime` có socket đích → `socket.emit(event, data, {cid, ts})` |
| Vào | client `socket.emit("<miền>.<việc>", data, ack)` → realtime gắn `claims` → `bw.rt.in` (durable, `alternate-exchange: bw.rt.in.unrouted`) → `@on_ws` |

Service `realtime` (Node 26, Socket.IO 4.8):
- cổng 8203;
- `GET /bizwithagents/ws/health`, `/bizwithagents/ws/metrics` (`bindings` đã xác nhận);
- Socket.IO `/bizwithagents/ws/socket.io/`, **chỉ websocket**;
- chỉ cần RabbitMQ + public key JWT.

Hai phía khai exchange cùng tham số (`names.py`); lệch → `PRECONDITION_FAILED`.

## 2. Routing key → phòng

| Routing key | Phòng | Nhận |
|---|---|---|
| `user.<id>` | `user:<id>` | mọi tab của user |
| `sup` | `sup` | mọi socket có claim `sup` |
| `all` | — | mọi socket + lệnh `rt:*` |

- **Binding động:** socket đầu tiên của một key → bind; socket cuối rời → unbind.
- Message tới lúc chưa bind xong bị bỏ (transient). Vì vậy smoke chờ `/ws/metrics` tăng rồi mới kích sự kiện.

## 3. API backend

```python
await emit_to_user(user_id, "core:notification", payload)
await emit_to_users(user_ids, event, data)
await emit_to_superadmins(event, data)
await emit_all(event, data)
await rt_revoke(sub, before=…, until=…)


@on_ws("<miền>.<việc>", permission=None, lane="default")
async def handler(ctx: WsContext, data: Model) -> None: ...
```

- Tên event ra `<miền>:<việc>`; tên event vào `<miền>.<việc>`.
- Handler `@on_ws` đặt ở `app/<miền>/consumers.py` (vd `system.ping`, `notifications.mark_read`) — luật `test_public_functions_in_ops_modules_are_operations` chỉ cho `@operation` / `ui_only` trong `ops.py`.
- Trong operation dùng `ctx.emit_*` / `ctx.invalidate` (gửi sau commit, R18).

## 4. Envelope v1 + kiểm chiều vào

- **Ra:** `{"v":1,"event","data","cid","ts"}`
- **Vào:** `{"v":1,"event","data","claims":{"sub","perms","sup"},"sid","cid","ts"}` — `claims` do service realtime gắn sau khi xác thực.

Kiểm chiều vào theo thứ tự; lỗi trả người gửi qua `sys:error {code, cid}`:

| Kiểm | Mã |
|---|---|
| `ts` cũ hơn `REALTIME_EVENT_MAX_AGE` (60 giây) | 1009 |
| user bị khoá (`bw:auth:disabled:<uid>`) | 2103 |
| thiếu quyền | 1005 |
| dữ liệu sai | 1002 |

## 5. Event lõi

| Event | Phát khi | Tới | Frontend |
|---|---|---|---|
| `data:changed {keys}` | sau mọi operation ghi | principal + `ctx.invalidate(users=…)` | `invalidateQueries` theo tiền tố |
| `core:notification {id, kind, title, body, params, action, read_at, created_at}` | `ctx.notify` sau commit | người nhận | toast + chuông; cùng lúc `PUSHED_HOOKS` gửi Web Push tới máy đã bật của người nhận khi app không mở (sp14, D97) |
| `core:rbac_updated {}` | gán / gỡ role, sửa quyền role | user bị ảnh hưởng | refresh token → `auth:refresh`, tải lại `me` |
| `core:account_disabled {}` | khoá tài khoản | user bị khoá | đăng xuất → `/login` |
| `rt:revoke {sub, before, until}` | khoá tài khoản | service realtime (`all`) | — (server ngắt socket) |
| `sys:error {code, cid}` | event client `@on_ws` bị từ chối / lỗi: `1009` quá hạn, `2103` bị khoá, `1005` thiếu quyền, `1002` dữ liệu sai, `1000` handler lỗi | người gửi | toast lỗi kèm "Mã tra cứu" |
| `system:pong {nonce, ts}` | trả lời event client `system.ping` (thử đường socket hai chiều) | người gửi | — (smoke / trang trạng thái) |

## 6. Xác thực socket

| Lúc | Kiểm |
|---|---|
| Handshake | access JWT: chữ ký public key, `typ=access`, chưa bị `rt:revoke` → join `user:<sub>` (+ `sup`). Sai → `connect_error "unauthorized"` |
| Token hết hạn | emit `auth:expired`; client refresh REST rồi gửi `auth:refresh {token}`; không làm mới trong 30 giây → ngắt |
| Khoá tài khoản | `rt:revoke` → mọi instance ngắt socket + từ chối token cũ tới khi hết hạn |

- Nối lại → refetch các query đã cũ; Header hiện trạng thái kết nối.
- **Proxy:** nginx chuyển `Upgrade` cho `/bizwithagents/ws/`; Cloudflare Tunnel cho websocket qua. Smoke prod phân biệt `unauthorized` (đã tới server) với lỗi transport (bị chặn).

## 7. Kiểm chứng

- `make rt-cov` ≥ 90%.
- Smoke: token sai → `unauthorized`; `core:rbac_updated`; `core:notification`; khoá user → ngắt + bắt tay lại bị từ chối.
- E2E: F3 / F4 / F7.

---

*Cập nhật: 2026-10-12*
