# Quyết định D1 →

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [decisions](./README.md) · [template-v1](../template-v1.md) · [roadmap](../roadmap.md)

---

## D1 — Template + module mẫu + công cụ tạo module · 2026-10-14

**Quyết định:** repo là một template chạy được như app thật, kèm một module mẫu chạy trọn các tầng và lệnh / skill tạo module mới. App mới = copy template + đổi tên.
**Lý do:** mỗi app sau chỉ thêm nghiệp vụ; module mẫu là khuôn cho scaffold.
**Đã loại:** chỉ có khung (phải tự dò cách làm); một repo chung cho nhiều app (các app dính chặt nhau khi deploy / nâng cấp).

## D2 — Giữ nguyên stack của dự án nguồn · 2026-10-14

**Quyết định:** Python 3.13 FastAPI + FastStream / taskiq trên RabbitMQ, service realtime Node + Socket.IO, React 19 + Vite + TanStack Query + Zustand + Tailwind 4 + Radix, Postgres + Redis (+ Mongo theo cờ), LangChain v1 / LangGraph, deploy Coolify.
**Lý do:** đã chạy thật trên prod, rủi ro thấp nhất.
**Đã loại:** bỏ RabbitMQ / Mongo, gộp realtime vào Python (phải viết lại, mất phần đã chạy thật).

## D3 — Tenant đơn giản: chỉ để tách dữ liệu khách hàng · 2026-10-14

**Quyết định:** tenant là ranh giới dữ liệu; agent giữ **một bộ như dự án nguồn** dùng chung cho mọi tenant. Chủ dự án chỉnh lại sau câu trả lời ban đầu "workspace, quyền theo từng workspace".
**Lý do:** hệ đa tenant nhiều tầng quá phức tạp để tích hợp agent; nhu cầu chính là tách dữ liệu từng khách hàng.
**Đã loại:** user ở nhiều workspace với role theo workspace; cấu hình agent riêng từng tenant.

## D4 — Web ưu tiên điện thoại + PWA, không native · 2026-10-14

**Quyết định:** một codebase web, thiết kế 375px trước, cài được lên màn hình chính, Web Push.
**Đã loại:** chuẩn bị sẵn cho app native; làm app Expo ngay.

## D5 — Đăng nhập: email + mật khẩu, Google, lời mời · 2026-10-14

**Quyết định:** email + mật khẩu (xác thực email, quên mật khẩu), Google OAuth, mời vào tenant bằng email hoặc link.
**Đã loại:** magic link / OTP (để sau).

## D6 — Mang sang đầy đủ hệ thống tài liệu + rule của dự án nguồn · 2026-10-14

**Quyết định:** giữ rule R1–R28 + rule riêng backend / frontend, nhật ký `D<n>`, plan theo SP (package R25), HLD + sơ đồ archify, `make docs` / `docs-check`; viết lại ví dụ, bỏ nội dung nghiệp vụ của dự án nguồn.
**Đã loại:** bản rút gọn (mất phần kiểm tự động link / backlink / số dòng).

## D7 — Đa ngôn ngữ, mặc định `vi`, có `en` · 2026-10-14

**Quyết định:** mọi chuỗi FE qua `t()`, từ điển `[vi, en]`; mail theo `users.locale`; agent trả lời theo ngôn ngữ của user.
**Đã loại:** chỉ tiếng Việt; chỉ tiếng Anh.

## D8 — Module mẫu: Tasks · 2026-10-14

**Quyết định:** quản lý công việc (trạng thái, ưu tiên, hạn, người làm, bình luận, nhắc hạn, chuyên gia agent).
**Lý do:** thể hiện đủ mọi tầng: CRUD, quyền, realtime, việc nền, thông báo, agent + duyệt.
**Đã loại:** Notes (ít realtime / việc nền); Flashcard (ít phân quyền).

## D9 — Tên cố định `bw` + `make new-app` đổi tên · 2026-10-14

**Quyết định:** template mang tên cố định (`BizWithAgents` / slug `bizwithagents` / tiền tố `bw`, cổng local 8201–8204, container 16811–16813); `make new-app` chép + đổi tên một lần.
**Lý do:** template tự chạy và test được như app thật; code giữ chuỗi literal; hai app dùng chung hạ tầng không đụng tiền tố.
**Đã loại:** tên đọc từ env lúc chạy (chuỗi ghép động, khó grep); cookiecutter (template không chạy thẳng được).

## D10 — Mỗi user thuộc đúng một tenant · 2026-10-14

**Quyết định:** `users.tenant_id` NOT NULL, claim `tid` trong JWT; không có bộ chuyển tenant; một email chỉ ở một tenant.
**Lý do:** agent và tool không phải biết tenant — lấy từ người đang chat.
**Đã loại:** user ở nhiều tenant + role theo tenant (cần tham số tenant ở tool, bộ chuyển ở UI).

## D11 — Tách dữ liệu bằng bộ lọc tự động ở session · 2026-10-14

**Quyết định:** model module kế thừa `TenantScoped`; session của op / việc nền mang `tenant_id`; SQLAlchemy `do_orm_execute` + `with_loader_criteria` tự thêm điều kiện, `before_flush` tự gán / kiểm; xem chéo chỉ qua `ctx.cross_tenant()` của superadmin. Test luật cấm SQL thô trên bảng tenant.
**Lý do:** quên lọc vẫn an toàn; không thêm gì vào migration; một choke-point.
**Đã loại:** tự lọc từng query (quên là lộ dữ liệu); Postgres RLS (policy mỗi bảng, khó gỡ lỗi); schema / DB riêng mỗi tenant (nặng).

## D12 — `signup_mode` quyết định người đăng ký vào tenant nào · 2026-10-14

**Quyết định:** `default_tenant` (mặc định — chạy như dự án nguồn) · `new_tenant` (mỗi người đăng ký có tenant riêng, là admin) · `invite_only`. Lời mời (email / link) chạy ở mọi chế độ. Role dùng chung mọi tenant, chỉ superadmin tạo role mới.
**Đã loại:** role riêng từng tenant (để TẦM NHÌN).

## D13 — Realtime: phòng `tenant:<tid>` · 2026-10-14

**Quyết định:** socket join phòng tenant lúc bắt tay theo claim `tid`; `ctx.invalidate(keys, tenant=True)` phát một message; sự kiện riêng vẫn tới `user:<id>`.
**Lý do:** user không đổi tenant nên không có join / leave động; `data:changed` chỉ mang key nên phát cả tenant không lộ dữ liệu.
**Đã loại:** gửi tới từng `user:<id>` (N message, phải tra danh sách user).

## D14 — Mail: `console` + `smtp` · 2026-10-14

**Quyết định:** interface transport; `console` (dev, có trang xem thư) và `smtp` (`aiosmtplib`); mẫu Jinja2 theo locale; gửi qua task idempotent. `email_verification` mặc định `soft`.
**Đã loại:** chỉ HTTP API một nhà cung cấp (không chạy local được nếu thiếu tài khoản).

## D15 — Module = package thường + registry tĩnh · 2026-10-14

**Quyết định:** backend `app/<module>/` thêm vào `DOMAINS`; frontend `src/modules/<module>/` thêm vào `modules/registry.ts`. Module đăng ký quyền, toolset, ngữ cảnh, chuyên gia, menu, "Thêm nhanh", widget qua hàm registry.
**Đã loại:** hệ plugin nạp động (phức tạp, migration theo module).

## D16 — Hạ tầng local mặc định bằng `deploy/compose.infra.yml` · 2026-10-14

**Quyết định:** Postgres / Redis / RabbitMQ / Mongo chạy bằng compose riêng của template trên cổng không đụng hạ tầng chung (15432 / 16379 / 5673 + 15673 / 27018); hạ tầng chung trên server là tuỳ chọn. Dev không bao giờ trỏ DB prod.
**Lý do:** clone về máy mới chạy được ngay; không đụng dữ liệu thật.
**Đã loại:** dev = prod như D41 của dự án nguồn.

## D17 — Thứ tự thi công: chép trọn nền trước, tổng quát hoá sau · 2026-10-14 · Claude tự quyết (uỷ quyền R28)

**Quyết định:** thay thứ tự SP trong [template-v1 §4](../template-v1.md): SP0 chép **trọn** phần nền (core, auth, system, observability, notifications, credentials, devtools, agent; realtime; frontend nền; deploy; tài liệu) rồi chạy test xanh; sau đó mới làm tenant + mail (SP1), tổng quát hoá agent (SP2), Tasks (SP3), scaffold (SP4), phát hành (SP5).

| Phương án | Code tạm phải viết để cắt phụ thuộc chéo | Test nguồn chạy lại được ngay | Số lần sửa cùng một file |
|---|---|---|---|
| **Chép trọn nền một lần** | ~0 | phần lớn | 1–2 |
| Chép từng mảng theo SP cũ | nhiều (core → observability, notifications → auth, system → auth / nhóm) | ít (phải stub) | 2–3 |

→ Chọn **chép trọn nền**: các miền nền của dự án nguồn import chéo nhau, tách theo SP cũ phải viết stub rồi bỏ.

## D18 — Plan dạng đặc tả · 2026-10-14 · Claude tự quyết (uỷ quyền R28)

**Quyết định:** plan SP là package R25 (`README.md` + `tNN-*.md` khi cần) dạng **đặc tả** (mục tiêu, file, giao diện, bước, DoD), không chép sẵn toàn bộ code mẫu vào plan.
**Lý do:** phần lớn việc là chép từ dự án nguồn — code nguồn đã có, plan chỉ cần ghi chép gì / sửa gì.
**Đã loại:** plan kèm code đầy đủ từng bước (gấp đôi khối lượng mà không thêm thông tin).

## D19 — Mô hình triển khai mặc định giống dự án nguồn (thay D16) · 2026-10-14

**Quyết định:** mọi app làm từ template mặc định dùng **hạ tầng có sẵn trên server** (Postgres — prod qua PgBouncer `6432`, Redis, RabbitMQ, Mongo); Coolify chỉ deploy **phần application** (6 service trong `compose.yml`, mạng riêng, nối hạ tầng qua IP host — như D36 / D40 của dự án nguồn). Mỗi app được cấp namespace riêng trên hạ tầng chung: DB `<slug>` / `<slug>_test` / `<slug>_e2e`, vhost cùng tên, một bộ Redis db riêng (dev / prod · test · stack thử), Mongo DB `<slug>`. Dev local nối cùng hạ tầng chung (`.env` trỏ vào cùng DB với bản deploy — như D41 của dự án nguồn). `deploy/compose.infra.yml` chỉ là **dự phòng** cho máy chưa có hạ tầng.
**Lý do:** chủ dự án: "thường sẽ có hạ tầng sẵn, chỉ cần deploy phần application như đang làm với Coolify".
**Redis db của template:** 10 (dev / prod) · 11 (test) · 12 (stack thử) — các db còn trống trên hạ tầng chung (đo 2026-10-14). `make new-app` phải nhận bộ số Redis db mới cho từng app (test xoá sạch db test của mình).
**Đã loại:** D16 — compose infra làm mặc định.

## D20 — Phiên chính tự làm cả test, không mở subagent (thay R22 / R26 kế thừa từ dự án nguồn) · 2026-10-15

**Quyết định:** phiên chính đọc code, viết code, viết + chạy test (unit, tích hợp, Playwright), debug. Không mở subagent trừ khi chủ dự án yêu cầu.
**Lý do:** chủ dự án: "tự làm đi, đừng spam agent, tốn token".
**Đã loại:** giao test cho một subagent Sonnet (R26 của dự án nguồn).

## D21 — Cho phép một subagent Sonnet 5.5 cho test Playwright (bổ sung D20) · 2026-10-15

**Quyết định:** test giao diện Playwright (E2E 375 / 1440) giao cho **một** subagent `model: sonnet`, `effort: medium` (R22). Mọi việc khác vẫn do phiên chính tự làm (D20).
**Lý do:** chủ dự án: "cho phép mở sub agent khi chạy test playwright với sonnet 5.5".

## D22 — Dữ liệu agent theo tenant: bảng hội thoại `TenantScoped`, usage / chặn / hạn mức giữ toàn nền tảng · 2026-10-15 · Claude tự quyết (uỷ quyền R28)

| Phương án | Bảng `TenantScoped` | Migration backfill | Op Studio / `/sa/*` phải `cross_tenant` | Báo cáo chi phí theo tenant |
|---|---|---|---|---|
| **A. Hội thoại scoped, số liệu toàn nền tảng có cột `tenant_id`** | `agent_sessions` · `agent_messages` · `agent_runs` · `agent_approvals` | 4 bảng + 1 cột usage | ít (op superadmin đã không scope) | ✓ (`group by tenant_id`) |
| B. Mọi bảng agent có người dùng đều scoped | thêm usage / chặn / hạn mức user | 7 bảng | nhiều (chặn spam + usage là màn superadmin) | ✓ |
| C. Không scope, lọc theo `user_id` như dự án nguồn | 0 | 0 | 0 | ✗ |

→ Chọn **A**: dữ liệu người dùng đọc / ghi qua trợ lý tự nằm trong tenant (D11); `agent_usage_hourly` thêm cột `tenant_id` (khoá chính) để `/sa/usage` lọc / gộp theo khách hàng; `agent_chat_blocks` · `agent_user_limits` là công cụ của superadmin nên giữ toàn nền tảng (ghi lý do ở `PLATFORM` của test B14). Span trace (Mongo) mang `tenant_id`.
**Đã cân nhắc:** B — scope bảng chỉ superadmin đọc chỉ thêm `cross_tenant` khắp nơi; C — một lỗi lọc `user_id` là lộ dữ liệu khách khác, trái D11.

## D23 — Mang SP17 của dự án nguồn (trả lời dạng stream + trang Cài đặt AI) vào SP2 · 2026-10-15 · Claude tự quyết (uỷ quyền R28)

| Phương án | Khối lượng | Lệch so với dự án nguồn sau SP2 | Rủi ro |
|---|---|---|---|
| **Chép SP17 (D111–D113 của dự án nguồn) trong SP2** | ~1 500 dòng (gồm test) | 0 | thấp — dự án nguồn đã chạy E2E 88 / 88 |
| Để sau v1 | 0 | tăng dần | về sau khó chép vì runtime agent đã tổng quát hoá |

→ Chọn **chép trong SP2**: công tắc `chat_stream` (mặc định bật) + `chat_stream_flush_ms`, tắt = gọi mô hình một lần; chữ hiện đều tay ở màn chat đơn giản; trang `/sa/ai-settings` gom cài đặt trợ lý (dùng chung `system.*_settings`).
**Đã cân nhắc:** để sau v1 — roadmap đã ghi "cân nhắc khi dự án nguồn code xong"; dự án nguồn xong 2026-10-15.

## D24 — Bỏ bảng `agent_usage_hourly` khỏi template (thay một phần D22) · 2026-10-15 · Claude tự quyết (uỷ quyền R28)

**Quyết định:** xoá model + migration `0006_agent_usage`; chi phí AI theo tổ chức đọc từ document Mongo `agent_llm_calls` (mang `tenant_id`) qua `usage.summary group_by=tenant`. `agent_runs.cost` (Postgres, theo tenant) vẫn cộng mỗi lượt.
**Lý do:** bảng đã thôi ghi từ SP6 của dự án nguồn (D64 bên dự án nguồn) — thêm `tenant_id` vào bảng không ai ghi là vô nghĩa; template chưa deploy nên bỏ migration không ảnh hưởng dữ liệu.
**Đã loại:** giữ bảng + thêm cột như D22 ghi (bảng chết, test phải nuôi).

## D25 — Registry module ở frontend: manifest tĩnh mỗi module · 2026-10-15 · Claude tự quyết (uỷ quyền R28)

| Phương án | Chỗ lõi phải sửa khi thêm module | Lazy load trang | Scaffold sinh được | Độ phức tạp |
|---|---|---|---|---|
| **Manifest tĩnh `src/modules/<m>/index.ts` + một dòng `registry.ts`** (nav, routes, quickAdd, widgets, dict) | 1 dòng | ✓ (`lazy()` trong manifest) | ✓ | thấp |
| Sửa thẳng `nav.ts` / `router.tsx` / `MobileDock` / Tổng quan / i18n cho từng module | 5 file | ✓ | khó (chèn vào nhiều file) | thấp nhưng dễ lệch |
| Nạp động theo cấu hình lúc chạy | 0 | ✓ | ✓ | cao |

→ Chọn **manifest tĩnh** — khớp D15 (package thường + registry tĩnh) ở backend; SP4 scaffold chỉ cần sinh thư mục + thêm một dòng.
**Đã cân nhắc:** sửa thẳng từng file (đúng như dự án nguồn làm, nhưng mỗi module chạm 5 chỗ lõi); nạp động (không cần cho template).

## D26 — Skill dùng chung cho Claude Code / Codex / Gemini · 2026-10-15 · Claude tự quyết theo yêu cầu chủ dự án

| Phương án | Agent dùng được | Chạy trên Windows | Lệch giữa các bản | Công sức |
|---|---|---|---|---|
| **Bản gốc `.agents/skills/` + bản sao `.claude/skills/`, `skills-check` trong CI** | Claude Code · Codex · Gemini | ✓ | CI bắt | thấp |
| Symlink `.claude/skills` → `.agents/skills` | như trên nếu agent theo symlink | ✗ (symlink git) | 0 | thấp |
| Chỉ `.claude/skills/` | Claude Code | ✓ | — | 0 |

→ Chọn **bản gốc `.agents/skills/` + bản sao kiểm bằng CI**: `.agents/skills` là chỗ chuẩn Agent Skills mà Codex và Gemini CLI cùng đọc; Claude Code đọc `.claude/skills`. `AGENTS.md` (Codex tự nạp; Gemini qua `.gemini/settings.json`) trỏ CLAUDE.md làm luật chung.
**Đã cân nhắc:** symlink (Codex theo symlink, Gemini / Claude chưa chắc; Windows hỏng); chỉ Claude (chủ dự án muốn dùng cả Gemini / OpenAI).

## D27 — Tạo app sau khi clone: đổi tên tại chỗ, giữ lịch sử, remote `template` · 2026-10-15 · Claude tự quyết theo yêu cầu chủ dự án

| Phương án | Bước người dùng | Kéo bản sửa của template về sau | Lịch sử git |
|---|---|---|---|
| **`make init-app` tại chỗ, commit đổi tên, `origin` → `template`** | clone → nói "tạo app" | `git fetch template` + merge (có xung đột ở dòng đổi tên) | giữ của template |
| Tại chỗ, xoá `.git` rồi `git init` | clone → nói "tạo app" | ✗ | mới |
| Chỉ `make new-app DEST=…` (chép sang thư mục khác) | clone template → tạo app ở thư mục khác | ✗ | mới |

→ Chọn **tại chỗ, giữ lịch sử + remote `template`**: đúng luồng "pull về rồi đổi tên"; còn đường lấy bản sửa của template. Chặn chạy nhầm trên bản template (thư mục tên `bizwithagents`) và khi cây git còn thay đổi chưa commit. `make new-app` vẫn giữ cho người tạo nhiều app từ một bản template.
**Đã cân nhắc:** lịch sử mới (mất đường cập nhật từ template); chỉ chép (thêm một thư mục thừa).

## D28 — `make setup`: một lệnh dựng môi trường, hạ tầng local hoặc chung · 2026-10-15 · Claude tự quyết theo yêu cầu chủ dự án

| Chế độ | Cần gì | Tự động hoàn toàn | Dùng khi |
|---|---|---|---|
| **`local` (mặc định của `setup`)** | Docker | ✓ (`make infra-up`, `.env` dùng dòng `# compose:`) | máy mới, máy người clone |
| `shared` (D19) | DB / vhost / Redis db do chủ dự án tạo trên hạ tầng chung | ✗ (điền mật khẩu vào `.env` rồi chạy lại) | máy có hạ tầng chung, server |

→ `setup` chạy lại vô hại, ghi `CREDENTIAL_KEYS` bền vào `.env` (thiếu khoá thì mỗi process dev tự sinh khoá tạm riêng → key LLM thêm ở Studio không giải mã được ở worker), không in secret (R21). D19 vẫn là mặc định khi deploy.
**Đã cân nhắc:** script hỏi tương tác (agent không trả lời được prompt TTY); chỉ hướng dẫn trong tài liệu (người dùng muốn làm bằng chat).
**Kèm theo:** đổi tên app dời cổng hạ tầng local + LLM giả +100 × (`PORTS` − 82) (Postgres 15432, Redis 16379, RabbitMQ 5673 / 15673, Mongo 27018, LLM giả 8799) — hạ tầng local của nhiều app chạy song song, không trùng nhau / trùng cổng app; DB dev không seed user test (luật `seed-test-users` chỉ cho `_test` / `_e2e`) — superadmin đầu tiên = đăng ký bằng email trong `SUPERADMIN_EMAILS`.

## D29 — Kéo bản sửa của template về app đã đổi tên: `make template-sync` · 2026-10-15 · chủ dự án duyệt đề xuất sau review SP6

| Phương án | File mới của template vào app mang tên app | Xung đột giả ở dòng đã đổi tên | Lần sau tính từ | Công sức |
|---|---|---|---|---|
| **`make template-sync`: đổi tên bản template đã đồng bộ + bản mới bằng luật của `init-app`, `cherry-pick` phần chênh** | ✓ | ✗ | `template_commit` trong `.template.json` | ~1 buổi |
| `git merge template/main` + grep tay | ✗ (lọt khi quên grep, git không báo) | ✓ mọi dòng template sửa có tên | merge-base | 0 |
| Chỉ playbook hướng dẫn sửa tay | ✗ | ✓ | — | thấp |

→ Chọn **`make template-sync`**: app ghi `.template.json` (tham số đổi tên + `template_commit`) lúc `init-app` / `new-app`; lệnh lấy `new_app.py` + `template_sync.py` mới nhất từ remote `template` (`git archive` → `debug/`, luật đổi tên luôn mới), dựng hai cây đã đổi tên, `cherry-pick` lên app → xung đột chỉ còn ở chỗ app và template cùng sửa; chặn khi cây chưa sạch / đang dở; cuối cùng kiểm còn tên template ở file vừa đổi (R11 — không âm thầm). App tạo bằng `new-app DEST` dùng được sau `git remote add template <url>`. `new-app-check` đi đường clone → `init-app` → template có bản sửa → `make template-sync`.
**Đã cân nhắc:** merge thẳng (tên template lọt qua file mới mà không xung đột; xung đột ở mọi dòng có tên); merge commit đã đổi tên thay `cherry-pick` (cần lịch sử chung giả, khó đọc hơn).
**Kèm theo (review SP6):** `make new-app` tự kiểm công cụ + cài `backend/.venv` (bản clone mới chưa có → `not found`); `init-app` / `new-app` kiểm công cụ ở chế độ `shared` (đổi tên không cần Docker); `README.md` gốc cho người mở repo trên GitHub.

## D30 — Repo public: quét secret + tên riêng trước push, tài liệu không ghi hạ tầng thật · 2026-10-15 · chủ dự án chốt phạm vi dọn; công cụ Claude tự quyết (uỷ quyền R28)

| Công cụ | Quét lịch sử git | Kiểm key còn sống | Chạy offline | Cài |
|---|---|---|---|---|
| **gitleaks + trufflehog (tuỳ chọn)** | ✓ | ✓ (trufflehog) | ✓ (gitleaks) | 1 binary mỗi công cụ, hoặc Docker |
| chỉ trufflehog | ✓ | ✓ | ✗ (luật generic yếu, ít bắt secret dạng `KEY = "…"`) | 1 binary |
| detect-secrets (Yelp) | ✗ (theo baseline file) | ✗ | ✓ | Python, baseline phải commit |
| chỉ GitHub secret scanning | ✓ sau khi push | một phần | — | 0 — nhưng chỉ báo **sau** khi đã lộ |

→ Chọn **gitleaks làm bước bắt buộc trong `make ci`, trufflehog tuỳ chọn**: gitleaks bắt cả secret dạng generic (lần quét đầu báo 10 chỗ — đều là giá trị giả trong test / PEM giữ chỗ trong tài liệu, đã ghi ngoại lệ hẹp), chạy offline trước push; trufflehog chỉ báo key còn sống nên ít báo sai. Thêm bước **tên riêng** đọc `.secrets/private-terms.txt` — danh sách nằm ngoài repo nên chặn được tên dự án khác / domain / IP mà không phải ghi chúng vào code (`test_no_source_refs.py` thôi chứa tên dự án nguồn).
**Phạm vi dọn (chủ dự án chốt):** tên dự án nguồn → "dự án nguồn"; domain → `<domain>` / `example.com`, `make smoke-prod` lấy `PUBLIC_URL` từ `.secrets/coolify.env`; IP / user DB / container / Redis db của app khác → chỗ giữ, giá trị thật ở `.secrets/`. Lịch sử git làm lại từ một commit (repo cũ còn email công ty và tên riêng ở các commit trước) — `template_commit` của app tạo trước mốc này không còn trong remote, `make template-sync` của các app đó phải đặt lại `.template.json`.
**Đã cân nhắc:** viết lại lịch sử bằng `git filter-repo` (giữ 8 commit nhưng phải lọc cả nội dung lẫn email, dễ sót); chỉ dựa GitHub secret scanning (báo sau khi đã public).

## D31 — Không port nghiệp vụ / realtime sang Go, giữ Python + Node · 2026-10-15 · chủ dự án chốt

Tải mục tiêu ~10k user, ~2k DAU. Ước lượng (giả định ~100 request / người / ngày): trung bình ~2–3 req/s, giờ cao điểm ~8 → ~25 req/s, ~200–500 socket đồng thời; lượt chat chủ yếu chờ LLM (I/O).

| Phương án | Công sức | Dư tải ở 2k DAU | Lõi (RBAC / tenant / envelope) | Agent gọi nghiệp vụ | Rủi ro |
|---|---|---|---|---|---|
| **Giữ Python + Node, đo rồi chỉnh** | giờ – ngày | ≥ 10× | 1 bản | cùng process (`@operation(agent=True)`) | thấp |
| Nghiệp vụ + realtime Go, agent Python | nhiều tuần (~12k dòng app + test) | lớn hơn, không cần tới | 2 bản (35 op của agent vẫn cần lõi) hoặc Go làm cửa duy nhất | qua mạng (danh mục op + gọi thay user) | cao |
| Chỉ realtime sang Go | ~0,8k dòng TS | như trên | 1 bản | cùng process | thấp, lợi ít |

→ Chọn **giữ stack**: ở quy mô này nút cổ chai là truy vấn DB / index, pool kết nối, chi phí + rate limit LLM — đổi ngôn ngữ không giải quyết. Không tạo branch `pythonnodejs` / `pygo`.
**Xem lại khi đo thấy:** CPU `bw-api` bão hoà dù `API_WORKERS` = số core mà p95 vẫn chậm; RAM cả stack vượt ngân sách server (thử gộp `consumer` / `worker` / `scheduler` vào một process trước); socket đồng thời hàng chục nghìn mỗi instance. Đo bằng load test (k6 / Locust) trên `make dev-up`.
**Đã cân nhắc:** port toàn bộ kể cả agent sang Go (hệ AI của Go chưa trưởng thành, mất checkpointer / trace LangGraph).

---

*Cập nhật: 2026-10-15*
