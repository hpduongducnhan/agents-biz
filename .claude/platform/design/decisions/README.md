# Nhật ký quyết định

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [template-v1](../template-v1.md) · [roadmap](../roadmap.md)

Mỗi mục là một quyết định **đã được chủ dự án chốt** (hoặc Claude tự quyết theo uỷ quyền R28 — ghi rõ). Thêm mục mới ở **cuối file mới nhất**, không sửa lịch sử; thay quyết định cũ thì thêm mục mới ghi "thay D<n>". File chạm 500 dòng (R25) → mở file mới và thêm hàng vào bảng dưới.

| File | Khoảng | Chủ đề |
|---|---|---|
| [d01-current](./d01-current.md) | D1 → | Hình thức template, stack, tenant, mobile, đăng nhập, tài liệu, i18n, module mẫu, đổi tên, tách dữ liệu, realtime, mail, module, môi trường local, thứ tự triển khai, mô hình triển khai giống dự án nguồn (D19), phiên chính tự test + subagent Playwright (D20–D21), dữ liệu agent theo tenant (D22, D24), stream chat (D23), registry module frontend (D25), skill đa agent (D26), đổi tên tại chỗ sau khi clone (D27), `make setup` (D28), `make template-sync` (D29) — **mục mới thêm ở cuối file này** |

## Quyết định kế thừa từ dự án nguồn

Template chép nền từ dự án nguồn nên giữ các quyết định sau của dự án đó (số D là số **bên dự án nguồn**, chỉ để tra nguồn):

| Số D nguồn | Nội dung giữ nguyên |
|---|---|
| D4 | Mongo chỉ để ghi log, tắt được bằng `MONGO_ENABLED` |
| D5 | Lịch sử chat lưu ở Postgres (`agent_messages` là nguồn sự thật) |
| D6 | Superadmin khai bằng env, toàn quyền |
| D7 | RBAC hệ thống: role có sẵn + role tự tạo, quyền cố định theo tính năng |
| D17 | Hook của agent là hook vòng đời |
| D18, D19 | Pool key theo agent + xoay vòng; rate limit đếm lượt + trần token |
| D20, D52 | Router theo ý định + chuyên gia, handoff |
| D21 | Mỗi lượt agent biết ngữ cảnh user; web và agent là hai client ngang nhau của cùng handler |
| D22 | Trace chỉ superadmin xem |
| D26 | Google OAuth chỉ để đăng nhập |
| D30 | Realtime-first |
| D33 | `.md` ≤ 500 dòng; plan mỗi sub-project là một package |
| D43 | Seed user test chỉ chạy trên DB `_test` / `_e2e` / `_dev` |
| D44 | Sinh type OpenAPI bằng package công cụ riêng `frontend/tools/openapi-ts` |
| D58 | File test / kịch bản kiểm ≤ ~800 dòng |
| D65–D68 | Màn chat đơn giản cho user + công tắc gỡ lỗi, phiên tự quản, giới hạn lịch sử |
| D80–D85 | Gom yêu cầu duyệt; quyền trợ lý theo user (`agent.<toolset>`), thao tác ghi rủi ro phải duyệt, trợ lý của superadmin `sup=False` |
| D92–D95 | Chống spam trợ lý: hạn mức phút / giờ / ngày, tự chặn tạm, chặn tay |
| D97–D99 | Web Push (VAPID tự sinh) |
| D110 | Không tạo artifact online; file xem thử / báo cáo lưu trong `.claude/` (R29) |

Kế thừa thêm theo D19: D36 / D40 (mạng riêng, nối hạ tầng chung qua IP host, Postgres qua PgBouncer), D37 (migrate ở đầu container api), D38 (khoá JWT trong env Coolify), D41 (dev dùng chung DB với bản deploy).

Không kế thừa: D1 (một tenant — thay bằng D3 ở đây), mọi quyết định về ví / nhóm / chia tiền / Drive / persona riêng của dự án nguồn.

---

*Cập nhật: 2026-10-14*
