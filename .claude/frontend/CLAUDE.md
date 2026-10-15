# CLAUDE.md — Frontend

> **Backlinks:** [CLAUDE.md](../../CLAUDE.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0). Rule chung ở [CLAUDE.md](../../CLAUDE.md) — file này **không chép lại**, chỉ ghi chi tiết riêng của frontend.

Một app **React 19 + TypeScript strict + Vite** ở `frontend/`: TanStack Query, Zustand, Tailwind 4 + Radix, react-router, react-hook-form + zod, socket.io-client, sonner, lucide, font Nunito.

## Menu tài liệu

| File | Trạng thái | Nội dung |
|------|-----------|----------|
| [ui-system](./design/ui-system.md) | ĐÃ CHỐT | Hiến pháp giao diện: ưu tiên điện thoại, token thương hiệu, bảng màu tối + vai `primary` (nền nút) / `brand` (chữ nhấn), bảng / thẻ (R16), `JsonView` (R17), dark / light, i18n, a11y, màn SP1, checklist |

Auth / guard / realtime phía client: [platform/auth-rbac §9](../platform/architecture/auth-rbac.md) · [backend/realtime](../backend/architecture/realtime.md).

## Cấu trúc

| Thư mục | Chứa |
|---|---|
| `src/lib/api/` | `openapi.json` (hợp đồng, dump từ backend) · `schema.d.ts` (sinh) · `endpoints.ts` (tên op → method + path) · `client.ts` (`call(op, input)`, mở envelope, refresh) · `url.ts` (`apiUrl`) · `errors.ts` |
| `src/lib/` | `keys.ts` (`mkKeys`), `query-client.ts`, `auth/`, `i18n/`, `realtime/` (`socket.ts`, `hooks.ts`), `date.ts`, `cn.ts` |
| `src/ui/` · `src/ui/shared/` | UI kit Radix · `Table`, `TruncText`, `json/JsonView`, `EmptyState`, `FormDialog`, `ConfirmDialog`… |
| `src/features/<miền>/` | `api.ts` (alias kiểu + gọi `call`) · `keys.ts` |
| `src/guards/` · `src/boot/` · `src/layout/` · `src/pages/` | guard route · router + realtime boot · AppShell (Header + `NavDrawer` ☰ điện thoại, Sidebar, `MobileDock` Trợ lý, `InstallGuide`); menu khai ở `layout/nav.ts` (`NavSection` + nhóm con `NavGroup` gập / mở, vẽ bởi `SidebarLinks.tsx`) · trang |
| `src/modules/` | module nghiệp vụ (D25): `types.ts` (`ModuleManifest`), `registry.ts` (`MODULES` — thêm một dòng mỗi module), `access.ts` (lọc theo quyền), `<module>/` (`index.ts` manifest · `api.ts` · `keys.ts` · `dict.ts` · `pages/` · `components/` · `widgets/`) — khuôn ở [tasks-module](../platform/architecture/tasks-module.md) |
| `src/features/agent/` · `src/pages/{assistant,studio}/` · `src/pages/sa/{Traces,TraceDetail,Usage}Page.tsx` | `store.ts` (áp `agent:*` theo `seq`, báo hở) + `useRunStream` (nghe realtime, bù `run_events`) · trang Trợ lý · Agent Studio · Trace + Usage — [agent-runtime](../platform/architecture/agent-runtime.md) |

## Rule gốc áp cho frontend — chi tiết riêng

| Rule gốc ([CLAUDE.md](../../CLAUDE.md)) | Ở frontend BizWithAgents |
|---|---|
| R6 envelope | mở **một** chỗ: `src/lib/api/client.ts`; lỗi `ApiError(status, code, correlationId, data)`; toast "Mã tra cứu: <cid>" |
| R7 OpenAPI | `npm run gen:api` sinh `schema.d.ts` từ `openapi.json` bằng bộ công cụ riêng `frontend/tools/openapi-ts` (TypeScript 5; `make fe-install` cài kèm); `make fe-api-check` trong `make ci`; chỉ `endpoints.ts` biết method + path |
| R9 ≤ ~400 dòng (test / kịch bản kiểm ≤ ~800) | trang lớn tách dialog / card ra file riêng |
| R14 phân trang | `limit` mặc định 20, dropdown / tra cứu `limit=100` |
| R15 JWT Bearer | access token chỉ trong bộ nhớ; refresh token `localStorage` `bw_refresh_token`; refresh single-flight + Web Locks `bw-auth-refresh`; URL qua `apiUrl()` |
| R16 bảng | `ui/shared/Table` + `TruncText` (Radix Tooltip, không `title`); dưới `md` danh sách là thẻ |
| R17 JSON | `ui/shared/json/JsonView` — call-site truyền thẳng giá trị |
| R18 realtime-first | socket một cửa `src/lib/realtime`; `data:changed` → `invalidateQueries` theo tiền tố `mkKeys` |
| R22 test giao diện | Playwright qua subagent Sonnet |

## Rule riêng của frontend (root chưa có)

1. **State đúng công cụ.** Data backend → TanStack Query, key `mkKeys("<miền>", …)` khớp `invalidates` của operation. UI state → Zustand (`stores/ui.store.ts`). Không nhồi data backend vào Zustand.
2. **Guard ở route.** `ProtectedRoute` · `RequirePermission` · `RequireSuperadmin` (`src/guards`). Thiếu quyền → `/403`. Trang không tự redirect.
3. **Realtime một cửa.** `useRealtime` / `useSendRealtime` / `useSocketStatus`; cấm tự gọi `io()`.
   - `core:rbac_updated` → refresh token + tải lại `me`.
   - `core:account_disabled` → đăng xuất về `/login`.
   - Nối lại → refetch query cũ.
4. **Env một cửa** `src/env.ts`.
5. **Quyền = mirror backend.** Hằng quyền khớp catalog (`user.view`, `user.manage`, `role.manage`, …); ẩn UI chỉ là UX.
6. **Ưu tiên điện thoại.** Thiết kế 375 trước; vùng bấm ≥ 44px; ô nhập 16px dưới `md`; dialog `max-h-[90dvh]`; không cuộn ngang ở 375 / 768 / 1024 / 1440 ([ui-system](./design/ui-system.md)).
7. **Chỉ semantic token**, không hex / màu Tailwind thô. Icon lucide, không emoji. Mọi chuỗi qua `t()`, mỗi key khai một lần `[vi, en]`.
8. **HTML thô phải sanitize**; lib nặng `lazy()` + `Suspense`.
9. **Ngày / giờ / số** qua `Intl` + helper (`lib/date.ts`); class động qua `cn()`.
10. **Banner khi tắt Mongo:** API đọc log trả `enabled: false` → `LogDisabledBanner`, không coi là lỗi.
11. **Trợ lý.**
    - Sự kiện `agent:*` chỉ nghe qua `useRunStream` (một cửa); sự kiện cũ / trùng `seq` bị bỏ, hở `seq` / nối lại → `agent.run_events`.
    - Trả lời của trợ lý hiện bằng `<Markdown>` (`ui/shared/Markdown.tsx` — React node, không HTML thô; tiêu đề, danh sách lồng theo thụt đầu dòng, `>`, `---`); tham số / kết quả tool + thẻ duyệt dùng `JsonView` (R17).
    - Ô nhập chữ 16px ở điện thoại, dính đáy (trang Trợ lý không có cụm nút nổi); không bọc `<form>`, `autocomplete=off` để bàn phím không hiện thanh tự điền thẻ / địa chỉ / vị trí; lỗi 6001 / 6002 hiện "thử lại {time}" từ `retry_after_sec`, 6009 / 6010 hiện "chưa cấu hình" (+ link Studio cho superadmin).
12. **Sạch trước khi xong:** `make fe-lint fe-typecheck fe-cov fe-build fe-api-check` (độ phủ ≥ 80%); không `any`.

---

*Cập nhật: 2026-10-15*
