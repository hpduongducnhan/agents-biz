# SP3 — Module mẫu Tasks

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [roadmap](../../design/roadmap.md) · [template-v1 §3.4, §3.6](../../design/template-v1.md) · [decisions](../../design/decisions/d01-current.md) · [tenancy](../../architecture/tenancy.md) · [agent-runtime](../../architecture/agent-runtime.md) · [sp2-agent-general](../sp2-agent-general/README.md)

**Trạng thái:** **Xong** (2026-10-15) — plan dạng đặc tả (D18). Kết quả ở [roadmap](../../design/roadmap.md); tài liệu module: [tasks-module](../../architecture/tasks-module.md); E2E `scripts/e2e/sp3_tasks_ui.py`.

## Goal

Module nghiệp vụ đầu tiên làm mẫu cho mọi module sau (và cho scaffold SP4): quản lý công việc của một tổ chức — làm được mọi việc bằng web **và** bằng chat, người cùng tổ chức thấy thay đổi ngay, dữ liệu tách theo tenant mà code module không nhắc tới tenant.

## Architecture

**Backend `app/tasks/`** (khuôn template-v1 §3.4):

| File | Nội dung |
|---|---|
| `models.py` | `Task(TenantScoped)`: `title` ≤ 200 · `description` (text) · `status` `todo \| doing \| done \| cancelled` · `priority` `low \| normal \| high \| urgent` · `due_at` · `assignee_id` (FK users, SET NULL) · `position` (float — kéo thả) · `created_by` · `source` `web \| agent` · `agent_run_id` · `completed_at` · `created_at` · `updated_at`; index `(tenant_id, status, due_at)`, `(tenant_id, assignee_id)`. `TaskComment(TenantScoped)`: `task_id` (CASCADE) · `author_id` · `body` ≤ 4 000 · `created_at` |
| `permissions.py` | `tasks.view` · `tasks.edit` · `tasks.delete`; role: admin = cả ba, member = view + edit, viewer = view |
| `errors.py` | dải `10001–10099` (owner `tasks` trong `ERROR_RANGES`): 10001 không tìm thấy việc · 10002 người được giao không cùng tổ chức · 10003 chuyển trạng thái không hợp lệ |
| `ops.py` | `tasks.list` (lọc `status[]`, `assignee_id` / `mine`, `due` `overdue \| today \| week`, `q` chữ, sắp `due_at` / `position` / `updated_at`; R14) · `tasks.get` · `tasks.create` · `tasks.update` · `tasks.assign` · `tasks.set_status` · `tasks.delete` (`destructive` → qua trợ lý phải duyệt) · `tasks.comments` / `tasks.add_comment` · `tasks.summary` (đếm theo trạng thái, quá hạn, của tôi). Mọi op ghi: `invalidates=("tasks.list", "tasks.detail", "tasks.summary")` + `ctx.invalidate(..., tenant=True)`; `agent=True, toolset="tasks"` trừ khi ghi lý do |
| `service.py` | luật: `done` → `completed_at`; giao việc kiểm user cùng tenant (bảng `users` đã scope → không thấy là 10002); `source=agent` + `agent_run_id` khi `ctx.source == "agent"` |
| `agent.py` | `register_toolset("tasks", "Công việc: xem, tạo, sửa, giao, bình luận", confirm_writes={"tasks.delete"})` · `register_context("tasks", …, router=True)` (đếm theo trạng thái + 5 việc gần hạn của tôi) · `register_specialist(SpecialistSeed(slug="tasks", …))` + `prompts/tasks.md` |
| `tasks.py` | cron `tasks.due_reminders` (`*/15 * * * *`): đọc việc sắp hạn (≤ 24 giờ) / quá hạn bằng `ALL_TENANTS`, gom theo tenant, thông báo người được giao trong `tenant_session`; idempotent bằng Redis `rkey("tasks", tid, "remind", task_id, mốc)` |
| `qkeys.py` | `tasks.list` · `tasks.detail` · `tasks.summary` |

Thông báo: được giao việc / có bình luận mới trên việc của mình → `notify_users` (kind `tasks.assigned` / `tasks.commented`, action mở việc) + Web Push (đã có ở nền). Log `loc` tiền tố `tsk`. Migration `0009_tasks`.

**Frontend — registry module** (D25):

| Thành phần | Việc |
|---|---|
| `src/modules/registry.ts` | danh sách manifest module (một dòng mỗi module) |
| `src/modules/<module>/index.ts` | manifest: `id`, `nav` (mục menu + quyền), `routes` (trang lazy), `quickAdd` (nút ở cụm nút nổi + menu), `widgets` (thẻ trang Tổng quan), `dict` (i18n vi / en) |
| `layout/nav.ts`, `boot/router.tsx`, `MobileDock`, `OverviewPage`, `lib/i18n` | đọc registry — không sửa lõi khi thêm module |

**Frontend `src/modules/tasks/`:** `api.ts` · `keys.ts` · `pages/TasksPage.tsx` (bộ lọc trên URL; thẻ ở điện thoại / bảng ở desktop — R16; nhóm theo trạng thái) · `components/TaskSheet.tsx` (chi tiết: sửa nhanh trường, giao việc, đổi trạng thái, bình luận) · `components/TaskForm.tsx` (hộp thoại tạo / sửa) · `components/QuickAdd.tsx` (tiêu đề + hạn + người làm) · `widgets/MyTasksWidget.tsx` ("Việc của tôi": quá hạn / hôm nay / sắp tới).

## Global Constraints

- Code module không nhắc tới tenant (trừ cron đọc chéo có lý do — B14); bảng mới kế thừa `TenantScoped`, test B14 không thêm gì vào `PLATFORM`.
- Không sửa lõi agent để thêm Tasks — chỉ `agent.py` của module (kiểm SP2).
- Realtime: người cùng tổ chức thấy thay đổi ngay; tổ chức khác không nhận `data:changed` của Tasks.
- i18n vi / en đầy đủ; mobile-first 375.

## Tasks

| # | Việc | Kết quả |
|---|---|---|
| T1 | Backend model + migration + quyền + lỗi + `loc` | `0009_tasks`; test model, B14 xanh |
| T2 | Op + service + realtime | 11 op; test BE: CRUD, lọc, phân trang, quyền theo role, tách tenant (404 chéo tổ chức), giao việc chéo tổ chức → 10002, `invalidates` + phòng tenant |
| T3 | Thông báo + cron nhắc hạn | test idempotent (chạy cron 2 lần không nhắc trùng), chỉ nhắc đúng tenant |
| T4 | Agent | toolset + ngữ cảnh + chuyên gia + prompt; test LLM giả: tạo / giao / đổi trạng thái / xoá (phải duyệt) qua chat; câu ý định `tests/agent_eval/tasks_{vi,en}.yaml` ≥ 30 câu mỗi ngôn ngữ (chạy `make agent-eval` khi có key LLM thật — việc của chủ dự án) |
| T5 | Registry module frontend (D25) | manifest + nav / router / dock / Tổng quan đọc registry; test FE |
| T6 | UI Tasks | trang danh sách, sheet chi tiết, form, Thêm nhanh, widget; test FE (thẻ / bảng, lọc URL, realtime `data:changed`) |
| T7 | Tài liệu | doc module mẫu `architecture/tasks-module.md` (khuôn cho module sau), template-v1 trỏ tới, roadmap |
| T8 | Kiểm + release | `make ci`; smoke thêm: tạo việc ở tổ chức A → user tổ chức B không thấy / không nhận realtime; E2E Playwright (subagent — R22): tạo / sửa / giao / bình luận / xoá qua web và qua chat, người cùng tổ chức thấy ngay (2 context), 375 / 1440 |

## Definition of Done

- `make ci` xanh; smoke-local hai chế độ Mongo xanh (có bước Tasks).
- E2E: mọi việc làm được bằng web và bằng chat; xoá qua chat phải duyệt; người cùng tổ chức thấy ngay không tải lại trang; tổ chức khác không thấy.
- Thêm module mới chỉ cần: package backend + một dòng `DOMAINS` + thư mục `src/modules/<module>/` + một dòng `registry.ts`.

## Self-Review

- Cron đọc chéo tenant là ngoại lệ duy nhất của module — đọc bằng `ALL_TENANTS`, ghi / thông báo trong `tenant_session` của từng tenant.
- `position` dạng float để chèn giữa không phải đánh lại số; danh sách mặc định sắp theo hạn, kéo thả để SP sau nếu cần.
- Thực tế làm: bỏ op `tasks.comments` riêng (`tasks.get` kèm 100 bình luận), thêm `tasks.people` (trợ lý tìm người theo tên để giao việc); 10 op. Lõi chạy provider ngữ cảnh của module trong session đã scope theo tenant. Test lõi đổi sang "lõi cố định + module tuỳ ý" (miền, dải mã lỗi, toolset, quyền, chuyên gia) để module mới không làm đỏ test lõi.
- Sau E2E: nút gửi bình luận `shrink-0` (44 px ở 375); ô hạn chiếm cả hàng ở điện thoại; xoá việc tắt query chi tiết ngay khi bắt đầu (`data:changed` tới trước phản hồi HTTP → từng tải lại 404). Người khác đang mở việc bị xoá vẫn nhận 404 → "Không tìm thấy công việc" (đúng).

---

*Cập nhật: 2026-10-15*
