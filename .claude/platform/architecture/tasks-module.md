# Platform — Module mẫu Tasks (khuôn cho mọi module)

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [platform/CLAUDE.md](../CLAUDE.md) · [template-v1 §3.4, §3.6](../design/template-v1.md) · [plan SP3](../plans/sp3-tasks-module/README.md) · [tenancy](./tenancy.md) · [agent-runtime](./agent-runtime.md) · [decisions D15, D25](../design/decisions/d01-current.md)

**Trạng thái:** ĐÃ CHỐT (SP3). Code: `backend/app/tasks/`, `backend/migrations/versions/0009_tasks.py`, `backend/tests/tasks/`, `backend/tests/agent_eval/tasks_{vi,en}.yaml`, `frontend/src/modules/{registry,access,types}.ts`, `frontend/src/modules/tasks/`, `frontend/test/modules/tasks.test.tsx`.

Công việc của một tổ chức: tạo, sửa, giao, đổi trạng thái, bình luận, xoá, nhắc hạn — làm được bằng web **và** bằng trợ lý; người cùng tổ chức thấy ngay; tổ chức khác không thấy. Code module **không nhắc tới tenant** (trừ cron đọc chéo — B14).

## 1. Thêm một module mới — các chỗ phải chạm

`make new-module NAME=<m> TITLE="…" [TITLE_EN="…"]` làm sẵn cả 9 chỗ dưới đây (khung CRUD theo khuôn này, mẫu ở `scripts/scaffold/templates/module/`) — xem [playbooks](../playbooks/README.md). `make scaffold-check` (trong `make ci`) giữ mẫu không lỗi thời.

| # | Chỗ | Việc |
|---|---|---|
| 1 | `backend/app/<m>/` | package theo khuôn §2 |
| 2 | `backend/app/domains.py` | một dòng ở `DOMAINS` |
| 3 | `backend/app/core/errors.py` · `core/logging.py` | dải mã `1NNxx` ở `ERROR_RANGES` · tiền tố `loc` ở `LOG_PREFIXES` (test luật kiểm) |
| 4 | `backend/app/models/__init__.py` | import model (Alembic thấy bảng) |
| 5 | `backend/migrations/versions/00NN_<m>.py` | nối sau head hiện tại (test lấy head động — `head_revision()`) |
| 6 | `backend/tests/<m>/` + `tests/agent_eval/<m>_{vi,en}.yaml` | test §6; ≥ 30 câu ý định mỗi ngôn ngữ |
| 7 | `frontend/src/modules/<m>/` | khuôn §4 |
| 8 | `frontend/src/modules/registry.ts` | một dòng ở `MODULES` |
| 9 | `frontend/src/lib/api/endpoints.ts` | op → method (test hợp đồng kiểm GET / POST) |

Không sửa lõi agent, menu, router, Tổng quan, i18n — lõi đọc registry (D15, D25).

## 2. Backend `app/tasks/`

| File | Nội dung |
|---|---|
| `__init__.py` | import `errors`, `permissions`, `notify` (đăng ký khi nạp miền) |
| `models.py` | `Task(TenantScoped)` · `TaskComment(TenantScoped)` — trạng thái `todo \| doing \| done \| cancelled`, ưu tiên `low \| normal \| high \| urgent`, `source` `web \| agent` + `agent_run_id` |
| `permissions.py` | `tasks.view` · `tasks.edit` · `tasks.delete`; admin = cả ba · member = view + edit · viewer = view |
| `errors.py` | 10001 không tìm thấy việc (404 — kể cả việc của tổ chức khác) · 10002 người được giao không thuộc tổ chức (422) |
| `schemas.py` · `service.py` | input / output; luật dùng chung (đọc việc, kiểm người làm, khoảng hạn theo múi giờ user, dựng output kèm tên) |
| `ops.py` | 10 op (§3) |
| `notify.py` | loại thông báo `task_assigned` · `task_commented` · `task_due_soon` · `task_overdue` (`register_kind`) |
| `agent.py` | `register_toolset("tasks", …)` · `register_context("tasks", …)` · `register_specialist(SpecialistSeed("tasks", …))` + `prompts/tasks.md` |
| `tasks.py` | cron `tasks.due_reminders` |
| `qkeys.py` | `tasks.list` · `tasks.detail` · `tasks.summary` |

## 3. Operation

| Op | Method | Quyền | Trợ lý | Ghi chú |
|---|---|---|---|---|
| `tasks.list` | GET | view | ✓ | lọc `status` / `open_only`, `mine` / `assignee_id`, `due` (`overdue` · `today` · `week` · `none`), `q`; sắp `due` (không hạn cuối) / `updated` / `created` / `priority`; R14 |
| `tasks.get` | GET | view | ✓ | kèm 100 bình luận gần nhất |
| `tasks.summary` | GET | view | ✓ | đếm theo trạng thái, quá hạn, hôm nay, của tôi |
| `tasks.people` | GET | view | ✓ | người đang hoạt động trong tổ chức (id + tên) — giao việc |
| `tasks.create` · `tasks.update` · `tasks.assign` · `tasks.set_status` · `tasks.add_comment` | POST | edit | ✓ | `update` chỉ đổi trường gửi lên (`due_at: null` bỏ hạn) |
| `tasks.delete` | POST | delete | ✓ (`destructive` → luôn phải duyệt) | xoá cả bình luận |

- **Realtime (R18):** mọi op ghi khai `invalidates` + `ctx.invalidate(qkeys.ALL, tenant=True)` → phòng `tenant:<tid>`; tổ chức khác không nhận.
- **Thông báo:** được giao việc (người khác giao) → người làm; bình luận → người làm + người tạo (trừ người viết). Bấm mở `/tasks?task=<id>`.

## 4. Frontend

| File | Việc |
|---|---|
| `modules/types.ts` | `ModuleManifest`: `nav` · `routes` · `quickAdd` · `widgets` · `dict` (mỗi mục có `perm` tuỳ chọn) |
| `modules/registry.ts` | `MODULES` — chỉ import manifest (nhẹ) |
| `modules/access.ts` | `moduleNav` / `moduleQuickAdds` / `moduleWidgets` lọc theo quyền |
| `layout/nav.ts` · `boot/router.tsx` · `layout/MobileDock.tsx` · `pages/overview/OverviewPage.tsx` · `lib/i18n/register.ts` | đọc registry: mục menu chính (Tổng quan → module → Trợ lý), route có guard quyền, nút "Thêm nhanh" ở cụm nút nổi điện thoại, widget Tổng quan, từ điển |
| `modules/tasks/index.ts` | manifest Tasks |
| `modules/tasks/pages/TasksPage.tsx` | `/tasks`: Đang mở / Tất cả / Đã xong, "Của tôi", hạn, tìm — lọc trên URL; thẻ ở điện thoại / bảng ở desktop (R16); `?task=` mở chi tiết |
| `modules/tasks/components/TaskSheet.tsx` | chi tiết (bottom sheet): sửa nhanh từng trường, giao, trạng thái, bình luận, xoá (xác nhận) |
| `modules/tasks/components/TaskForm.tsx` | tạo việc — dùng ở trang + "Thêm nhanh" |
| `modules/tasks/widgets/MyTasksWidget.tsx` | "Việc của tôi": quá hạn / hôm nay / đang mở + 5 việc gần hạn |

## 5. Trợ lý

- Toolset `tasks` (quyền `agent.tasks` cho cả ba role có sẵn). Chuyên gia `tasks` ("Công việc"), route mặc định từ "Assistant" đứng trước `general`.
- Ngữ cảnh mỗi lượt: số việc theo trạng thái của tổ chức + ≤ 5 việc đang mở gần hạn của người chat (kèm id) — lõi chạy provider trong session đã scope theo tenant của user.
- Việc tạo / bình luận qua trợ lý: `source=agent` (+ `agent_run_id`), giao diện gắn nhãn "Tạo bởi trợ lý".
- Câu ý định: `tests/agent_eval/tasks_{vi,en}.yaml` (32 + 32). `bw agent-eval` đọc mọi `*.yaml` trong thư mục — cần key LLM thật.

## 6. Kiểm

- BE `tests/tasks/`: CRUD, lọc / sắp / phân trang, quyền theo role, tách tổ chức (404, giao chéo 10002), thông báo, `data:changed` tới phòng tenant, chat qua LLM giả (tạo `source=agent`, xoá phải duyệt, tool không chạm tổ chức khác), ngữ cảnh, cron nhắc hạn idempotent.
- FE `test/modules/tasks.test.tsx`: trang (thẻ / bảng, lọc URL, rỗng), tạo, chi tiết (trạng thái, giao, tiêu đề, bình luận, xoá), viewer chỉ xem, widget, registry theo quyền.
- Smoke: bước Tasks (tạo ở tổ chức mới → tổ chức khác không thấy, không nhận `data:changed`). E2E: `scripts/e2e/sp3_tasks_ui.py`.

## 7. Bảng mặc định (R11)

| Khoá | Mặc định | Nguồn khi cấu hình |
|---|---|---|
| nhắc hạn | cron mỗi 15 phút; "sắp tới hạn" = trong 24 giờ; mỗi mốc (sắp / quá) của một hạn nhắc một lần (khoá Redis `bw:tasks:<tid>:remind:<task>:<mốc>:<hạn>`, 14 ngày) | code (`tasks.py`) |
| người nhận nhắc | người làm; chưa giao → người tạo | code |
| bình luận trong chi tiết | 100 gần nhất | code (`COMMENTS_SHOWN`) |
| danh sách | 20 / trang, tối đa 100 (R14); mặc định sắp theo hạn | input |
| hạn khi trợ lý không nghe giờ | 17:00 giờ người dùng | prompt `tasks.md` |

---

*Cập nhật: 2026-10-15*
