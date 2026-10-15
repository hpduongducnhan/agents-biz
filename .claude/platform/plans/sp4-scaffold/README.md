# SP4 — Scaffold module + tạo app mới

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [roadmap](../../design/roadmap.md) · [template-v1 §3.1, §3.4](../../design/template-v1.md) · [decisions D9, D15, D19, D25](../../design/decisions/d01-current.md) · [tasks-module](../../architecture/tasks-module.md)

**Trạng thái:** **Xong** (2026-10-15) — plan dạng đặc tả (D18). Kết quả ở [roadmap](../../design/roadmap.md); hướng dẫn dùng ở [playbooks](../../playbooks/README.md).

## Goal

Từ template ra một app mới chạy được trong vài phút (`make new-app`), và thêm một module nghiệp vụ CRUD đầy đủ (backend, trợ lý, frontend, test) bằng một lệnh (`make new-module`) — theo đúng khuôn của Tasks; CI giữ hai công cụ này không lỗi thời theo lõi.

## Architecture

**`make new-module NAME=notes TITLE="Ghi chú" [TITLE_EN="Notes"] [FIELDS=…]`** (`scripts/scaffold/new_module.py` + mẫu Jinja2 `scripts/scaffold/templates/module/`):

| Sinh ra | Theo khuôn |
|---|---|
| `backend/app/<m>/` — `__init__`, `models` (`TenantScoped`: `title`, `description`, `status` `open \| done`, `created_by`, `source`, `agent_run_id`, thời điểm), `schemas`, `service`, `ops` (list / get / create / update / delete — delete `destructive`), `permissions` (`<m>.view` · `.edit` · `.delete`, role như Tasks), `errors` (dải `1NNxx` kế tiếp), `qkeys`, `agent.py` (toolset + chuyên gia + ngữ cảnh đếm), `prompts/<m>.md` | [tasks-module §2](../../architecture/tasks-module.md) |
| `backend/migrations/versions/00NN_<m>.py` | nối sau head hiện tại |
| `backend/tests/<m>/` — CRUD, quyền theo role, tách tổ chức (404), `data:changed` phòng tenant, chat qua LLM giả (tạo / xoá phải duyệt) | `tests/tasks/` |
| `backend/tests/agent_eval/<m>_{vi,en}.yaml` — 5 câu mẫu mỗi ngôn ngữ + ghi chú "bổ sung ≥ 30" | |
| `frontend/src/modules/<m>/` — manifest, `api`, `keys`, `dict` (vi / en), `perms`, trang danh sách (thẻ / bảng, tìm, lọc trạng thái, URL), hộp thoại tạo / sửa, xoá có xác nhận; `frontend/test/modules/<m>.test.tsx` | `src/modules/tasks/` |
| Sửa một dòng ở: `DOMAINS`, `ERROR_RANGES`, `LOG_PREFIXES`, `app/models/__init__.py`, `src/modules/registry.ts`, `src/lib/api/endpoints.ts` | chèn có đánh dấu, chạy lại báo "đã có" (idempotent) |

Sau khi sinh: `make openapi fe-gen-api` + in checklist (sửa field, viết prompt, bổ sung câu ý định, chạy test). Tên module: chữ thường / số / gạch dưới, không trùng miền lõi.

**`make scaffold-check`** (trong `make ci`): sinh module `scaffoldcheck` vào **bản sao tạm** của repo (rsync bỏ `node_modules`, `.venv`, `.git` — dùng chung qua symlink), chạy `ruff`, test backend của module + test luật (B14, mã lỗi, `loc`, toolset), `fe-typecheck` + test frontend của module. Xoá bản sao.

**`make new-app NAME="Task Hub" SLUG=taskhub PREFIX=th DEST=../taskhub [PORTS=83] [REDIS_DBS=4,5,6]`** (`scripts/scaffold/new_app.py`, D9 + D19):

| Bước | Việc |
|---|---|
| chép | repo → `DEST`, bỏ `.git`, `.env`, `.secrets`, `debug/`, `.e2e/`, `.dev-stack/`, cache, `node_modules`, `.venv` |
| đổi tên | `BizWithAgents` → NAME · `bizwithagents` → SLUG (DB, vhost, đường dẫn `/<slug>/api`, `/<slug>/ws`, `SERVICE_PATH`) · tiền tố `bw` → PREFIX (CLI, Redis `bw:`, exchange `bw.*`, service `bw-*`, logger, `bw.assistant.view`…) — theo bảng thay thế có ranh giới từ, có danh sách loại trừ; đổi tên file / thư mục chứa tên |
| cổng | 82xx → `PORTS`xx (local 01–04, container 168xx tương ứng) |
| Redis db | 10 / 11 / 12 → bộ số mới (D19 — app dùng chung Redis không xoá nhầm db của nhau) |
| giữ nguyên bit thực thi | `scripts/*.sh`, `deploy/docker/*` |
| kết thúc | `git init` + commit đầu; in checklist chủ dự án: tạo DB / vhost trên hạ tầng chung, `.env`, khoá JWT (`<prefix> keys`), `SUPERADMIN_EMAILS`, Google OAuth, Coolify, domain |

**`make new-app-check`**: sinh app `qa` (prefix `qa`) vào thư mục tạm → grep tên cũ = 0 (trừ tài liệu nói về nguồn) → `ruff` + `fe-typecheck` + test đơn vị không cần hạ tầng (`-m "not integration"`) + `rt-typecheck`. Không chạy trong `make ci` (chậm) — chạy trước release (SP5).

**Skill Claude Code** `.claude/skills/new-module/SKILL.md` + `.claude/skills/new-app/SKILL.md`: hỏi gọn một lượt (nghiệp vụ, field, quyền, câu chat mẫu) → doc thiết kế module (ĐỀ XUẤT, bảng R4) → chạy scaffold → sửa field / luật → prompt + câu ý định → test (phiên chính) → E2E (subagent — R22) → tài liệu. Playbook ngắn ở `.claude/platform/playbooks/`.

## Global Constraints

- Scaffold sinh code đúng mọi rule (R6–R18, B1–B14, R9 ≤ 400 dòng / file) — `scaffold-check` là bằng chứng.
- Không sửa lõi ngoài 6 dòng đăng ký; chạy lại lệnh không nhân đôi dòng.
- `new-app` không đọc / chép secret.

## Tasks

| # | Việc | Kết quả |
|---|---|---|
| T1 | Mẫu Jinja2 backend + frontend + test (rút từ Tasks, bỏ phần riêng: giao việc, hạn, bình luận, cron) | `scripts/scaffold/templates/module/` |
| T2 | `new_module.py` + chèn dòng đăng ký idempotent + `make new-module` | test `scripts/tests/test_scaffold.py` (sinh vào thư mục tạm, kiểm file + chèn dòng) |
| T3 | `make scaffold-check` vào `make ci` | xanh |
| T4 | `new_app.py` + `make new-app` + `make new-app-check` | test đổi tên (bảng thay thế, cổng, Redis db, bit thực thi) + chạy check |
| T5 | Skill + playbook | `.claude/skills/{new-module,new-app}/SKILL.md`, `.claude/platform/playbooks/` |
| T6 | Tài liệu + kiểm | tasks-module §1 trỏ tới scaffold, deploy / CLAUDE.md, roadmap; `make ci` |

## Definition of Done

- `make new-module NAME=notes TITLE="Ghi chú"` → `make ci` xanh ngay, trang `/notes` chạy được, trợ lý tạo / xoá ghi chú được (LLM giả).
- `make new-app-check` xanh; app sinh ra `make dev-up` + `make smoke-local` được (chạy tay một lần trước release).

## Self-Review

- Mẫu Jinja2 lệch khỏi khuôn Tasks theo thời gian → `scaffold-check` trong CI bắt khi lõi đổi API.
- Thực tế làm: mẫu dùng token thay chuỗi (`__mod__`, `__Mod__`, `__title_vi__`…) thay cho Jinja2 — mẫu là code gần như chạy được, không đụng cú pháp `{{ }}` của JSX; thư mục mẫu loại khỏi ruff. Bộ sinh tự `ruff format` file sinh ra. `new-app` không chép công cụ chỉ của template (`new_app.py`, `check_app.sh`, skill `new-app`), sinh lại HTML tài liệu. Hook `pytest_collection_modifyitems` gắn `integration` cho test dùng fixture hạ tầng.
- Đổi tên bằng thay chuỗi dễ trúng nhầm (`bw` trong từ khác) → bảng thay thế theo ngữ cảnh (`bw:`, `bw.`, `bw-`, `bw_`, ` bw `, `"bw"`), có test liệt kê chỗ thay.

---

*Cập nhật: 2026-10-15*
