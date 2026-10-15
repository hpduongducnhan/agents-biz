---
name: new-module
description: Thêm một module nghiệp vụ (bảng + thao tác + trợ lý AI + giao diện + test) vào app làm từ template BizWithAgents. Dùng khi người dùng muốn thêm tính năng quản lý một loại dữ liệu mới (ghi chú, khách hàng, dự án, từ vựng…) hoặc nói "thêm module" (add a module / feature). Không dùng để tạo app mới (→ new-app) hay dựng môi trường (→ setup-env).
---

# Thêm module nghiệp vụ

Khuôn chuẩn là module mẫu Tasks — đọc `.claude/platform/architecture/tasks-module.md` trước. Làm theo `CLAUDE.md` (R1–R29, B1–B14) — áp dụng cho mọi agent. Claude Code: phiên chính tự viết code + test, chỉ Playwright giao subagent Sonnet (R22); agent khác tự làm hết trong phiên.

## 1. Hỏi một lượt (R4 — có khuyến nghị cho từng câu)

- Tên module (chữ thường / số / gạch dưới, vd `notes`) + tên hiển thị vi / en.
- Field nghiệp vụ (tên, kiểu, bắt buộc?, lọc theo?) — mặc định scaffold có `title`, `description`, `status open | done`.
- Quyền theo role có sẵn (mặc định: admin xem / sửa / xoá, member xem / sửa, viewer xem).
- Trợ lý cần làm gì bằng chat (3–5 câu mẫu) — có thao tác nào phải duyệt ngoài xoá không.
- Có việc nền (nhắc hạn, đồng bộ) / thông báo không.

## 2. Thiết kế

Viết `.claude/platform/architecture/<module>-module.md` (trạng thái ĐỀ XUẤT, bảng so sánh khi có ≥ 2 cách — R4), link từ `.claude/platform/CLAUDE.md`. Quyết định chủ dự án chốt → `D<n>` ở decisions.

## 3. Sinh khung

```bash
make new-module NAME=<module> TITLE="<tên vi>" TITLE_EN="<tên en>"
```

Lệnh sinh backend (`app/<module>/`, migration, test, câu ý định), frontend (`src/modules/<module>/`, test) và chèn một dòng ở 6 chỗ lõi; chạy lại `make openapi fe-gen-api`.

## 4. Sửa theo nghiệp vụ

1. `backend/app/<module>/models.py` + migration `00NN_<module>.py` (giữ `TenantScoped`, không SQL thô — B14).
2. `schemas.py` · `service.py` · `ops.py` (giữ `invalidates` + `ctx.invalidate(..., tenant=True)` — R18; op mới `agent=True` + `toolset` hoặc `agent_reason`).
3. `agent.py` (toolset, ngữ cảnh, chuyên gia) + `prompts/<module>.md` (tiếng Anh, có ví dụ vi / en).
4. `tests/agent_eval/<module>_{vi,en}.yaml` ≥ 30 câu mỗi ngôn ngữ.
5. Frontend: `api.ts` (đối chiếu `openapi.json` — R7), `dict.ts` (vi + en), `pages/`, `components/`, thẻ ở điện thoại / bảng ở desktop (R16); widget / "Thêm nhanh" khai trong `index.ts` nếu cần.
6. Test BE (`tests/<module>/`: CRUD, quyền, tách tổ chức 404, realtime, chat LLM giả) + FE (`test/modules/<module>.test.tsx`).

## 5. Kiểm + phát hành

`make ci` → `make dev-up MONGO=on|off` + `make smoke-local` (thêm bước của module nếu có luồng chéo tổ chức) → E2E Playwright 375 / 1440 (Claude Code: subagent Sonnet — R22; agent khác tự chạy, mẫu ở `scripts/e2e/`) → tài liệu (doc module ĐÃ CHỐT, roadmap, `make docs`) → commit (R27).
