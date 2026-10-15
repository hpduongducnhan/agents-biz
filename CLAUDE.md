# CLAUDE.md — BizWithAgents

| Mục | Link |
|-----|------|
| **Thiết kế tổng** | [template-v1](.claude/platform/design/template-v1.md) · [HLD + sơ đồ](.claude/HLD/HLD.md) |
| **Quyết định** | [decisions](.claude/platform/design/decisions/README.md) — D1… |
| **Lộ trình** | [roadmap](.claude/platform/design/roadmap.md) |
| **Plan** | [sp0-platform-port](.claude/platform/plans/sp0-platform-port/README.md) · [sp1-tenant-mail](.claude/platform/plans/sp1-tenant-mail/README.md) · [sp2-agent-general](.claude/platform/plans/sp2-agent-general/README.md) · [sp3-tasks-module](.claude/platform/plans/sp3-tasks-module/README.md) · [sp4-scaffold](.claude/platform/plans/sp4-scaffold/README.md) · [sp5-release](.claude/platform/plans/sp5-release/README.md) · [sp6-agent-skills](.claude/platform/plans/sp6-agent-skills/README.md) |
| **Platform** | [CLAUDE.md](.claude/platform/CLAUDE.md) — auth / RBAC, agent, menu plan |
| **Backend** | [CLAUDE.md](.claude/backend/CLAUDE.md) — rule B1–B14 · kết nối · logging · messaging · operation · realtime · quan sát |
| **Frontend** | [CLAUDE.md](.claude/frontend/CLAUDE.md) — rule riêng · [ui-system](.claude/frontend/design/ui-system.md) |
| **Deploy** | [CLAUDE.md](.claude/deploy/CLAUDE.md) — mô hình triển khai (D19), Coolify, môi trường local, stack thử, smoke |
| **Agent + skill** | [README.md](README.md) — bắt đầu nhanh · [AGENTS.md](AGENTS.md) — Codex / Gemini đọc luật ở file này · skill `new-app`, `setup-env`, `new-module` ở `.agents/skills/` (bản sao `.claude/skills/` — D26) · [playbooks](.claude/platform/playbooks/README.md) |
| **Trang review (HTML)** | [.claude/index.html](.claude/index.html) — sinh bằng `make docs` (R23) |
| **Quick ref** | [Project Context](#project-context) · [Rule](#rule--áp-dụng-mọi-session) |

---

## Project Context

**BizWithAgents** — template fullstack có sẵn trợ lý AI. Mỗi app mới (quản lý dự án, việc cá nhân, học tiếng Anh, học system design…) = clone template → đổi tên tại chỗ (`make init-app`) → dựng môi trường (`make setup`) → thêm module nghiệp vụ (`make new-module`); bản sửa của template kéo về bằng `make template-sync`. Phần nền chép từ dự án nguồn (đã chạy thật trên prod): đăng nhập + RBAC + superadmin từ env, realtime, thông báo + Web Push, event log / issues, agent (orchestrator + chuyên gia, Studio, trace / usage, duyệt, hạn mức), khung UI ưu tiên điện thoại + PWA, deploy Coolify. Tenant đơn giản: chỉ để tách dữ liệu từng khách hàng, agent một bộ dùng chung (D3).

**Trạng thái:** thiết kế tổng ĐÃ CHỐT (D1–D31). SP0–SP6 xong 2026-10-15 — template **`v1.2.0`** (chép nền, tenant + mail, agent tổng quát, module mẫu Tasks, scaffold `make new-module` / `make new-app`, kiểm + phát hành, skill cho Claude Code / Codex / Gemini + `make init-app` / `make setup` / `make template-sync`); việc còn lại là của chủ dự án (repo GitHub, hạ tầng chung, Coolify) — xem [roadmap](.claude/platform/design/roadmap.md).

**Stack:** Python 3.13 (FastAPI, FastStream + taskiq trên RabbitMQ, SQLAlchemy/SQLModel + psycopg3, Alembic, Redis, Beanie khi bật Mongo, LangChain v1 / LangGraph) · service realtime Node + Socket.IO · React 19 + TypeScript + Vite + TanStack Query + Zustand + Tailwind 4 + Radix · Postgres + Redis + RabbitMQ (+ Mongo nếu `MONGO_ENABLED`) · deploy Coolify, hạ tầng chung có sẵn trên server (D19).

---

## Rule — áp dụng mọi session

### A. Tài liệu và quyết định

**R1 — Luôn cập nhật tài liệu kiến trúc.** Gặp kiến trúc mới, tính năng quan trọng hay pattern đáng chú ý thì:
1. Cập nhật file tương ứng trong `.claude/<domain>/{architecture,design,plans}/`.
2. Thêm link vào menu của domain hoặc root.
3. Ghi `*Cập nhật: YYYY-MM-DD*` ở cuối file.
4. Chạy `make docs` rồi commit cả `.html`.

**R2 — Backlink bắt buộc.** Mọi file `.md` trong `.claude/` (kể cả file con trong package) có ngay sau H1 dòng:
```markdown
> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [file-liên-quan](./file-lien-quan.md)
```
- File con trong package (R25) link thêm về `README.md` của package và file kề.
- File mới phải được link từ menu (root, `.claude/<domain>/CLAUDE.md` hoặc `README.md` của package) — không để file mồ côi.
- Kiểm bằng `python3 scripts/check_md.py` (nằm trong `make docs-check`).

**R3 — Quyết định ghi thành `D<n>`, kèm trạng thái.**
- Mỗi quyết định chủ dự án chốt → thêm mục `D<n>` **ở cuối file mới nhất** của package [decisions](.claude/platform/design/decisions/README.md): quyết định, lý do, phương án đã loại. Không sửa mục cũ; thay thì ghi "thay D<n>".
- Mỗi doc thiết kế ghi trạng thái ở đầu: **ĐÃ CHỐT** · **ĐỀ XUẤT** · **TẦM NHÌN**. Không code theo thứ đang ĐỀ XUẤT.
- Comment trong code chỉ nhắc `D<n>` của template này; số / tài liệu của dự án nguồn đã dọn ở SP5 (bảng kế thừa ở [decisions](.claude/platform/design/decisions/README.md)), test luật `test_no_source_refs.py` chặn `v1-design` / `sp*-index` trong code; tên riêng (dự án nguồn, domain, IP) chặn bằng `make secrets-scan` với danh sách cục bộ `.secrets/private-terms.txt`.

**R4 — Đề xuất và plan / design phải có bảng so sánh.** Khi có ≥ 2 phương án / chế độ / mức độ, đặt **bảng so sánh ngay chỗ cần quyết định**:
1. Mỗi hàng là một phương án; cột đầu là tên phương án.
2. Mỗi cột là một tiêu chí cụ thể, đo được: chi phí / token, số migration, đổi hành vi?, độ phức tạp, rủi ro… **Không** dùng cột chung chung kiểu "ưu / nhược".
3. Ô dùng ký hiệu quét nhanh (`✓` / `✗` / `—`, số, từ khoá ngắn), tránh câu dài.
4. Ngay dưới bảng có dòng khuyến nghị `→ Chọn X vì …`, kèm mục **Đã cân nhắc** (phương án loại + lý do).

Câu hỏi đưa chủ dự án cũng vậy: luôn có phương án khuyến nghị và cái giá của từng phương án, không hỏi trống. Hỏi tối đa một lượt gọn; phần còn lại theo khuyến nghị.

**R5 — Không ghi kiến trúc vào comment code.** Kiến trúc thuộc `.claude/`, không thuộc docstring hay comment.

**R25 — Mỗi file `.md` tối đa 500 dòng; dài hơn thì tách thành package.**
- **Plan:** mỗi sub-project là một thư mục `plans/<sp>/`: `README.md` (Goal, Architecture, Global Constraints, Tasks, DoD, Self-Review) + `tNN-<slug>.md` khi task dài. Plan dạng đặc tả (D18).
- **Design dài:** thư mục cùng tên, `README.md` là tổng quan + mục lục, mỗi file con một nhóm mục.
- Kiểm: `python3 scripts/check_md.py` (số dòng, backlink, link hỏng, file mồ côi).

**R29 — Không tạo artifact online; mọi file xem thử / báo cáo lưu trong `.claude/`** (kế thừa D110 của dự án nguồn).
- Không publish lên claude.ai (Artifact) hay dịch vụ ngoài: bản xem thử giao diện, mockup, trang so sánh, báo cáo.
- File HTML tự chứa đặt cạnh tài liệu liên quan, vd `.claude/platform/design/previews/<sp>.html`; link từ doc thiết kế, mở bằng trình duyệt. Không có dấu sinh của `make docs` nên `docs-check` không coi là thừa.
- Nội dung dạng chữ vẫn là `.md` theo R1 / R2 / R25.

### B. Backend

**R6 — Mọi response theo envelope `ApiResponse`.** Mọi endpoint — `@operation` lẫn route viết tay `ui_only` — trả `{success, code, message, data, correlation_id}`. Frontend chỉ có **một** chỗ mở envelope (`frontend/src/lib/api/client.ts`): `success=true` thì lấy `data`; ngược lại ném `ApiError(code, message, data, cid)`.

**R7 — OpenAPI là hợp đồng duy nhất giữa backend và frontend.**
- `bw dump-openapi` (`make openapi`) ghi `frontend/src/lib/api/openapi.json`; `make fe-gen-api` sinh `schema.d.ts`.
- Thêm / sửa API client, type, mock ở frontend thì **đối chiếu file này trước**, không đoán shape.
- Backend đổi operation hay schema → dump lại và commit cùng thay đổi.

**R8 — Import Python đặt ở đầu file (module level), kể cả trong test.** Ngoại lệ duy nhất là tránh vòng import, kèm comment `# defer: tránh vòng import với <X>`.

**R9 — Mỗi file code tối đa ~400 dòng** (`.py`, `.ts`, `.tsx`).
- Chạm ngưỡng thì tách theo trách nhiệm, không cắt cơ học giữa hàm.
- Miền / module lớn tách **package theo tính năng**: `app/<miền>/<tính-năng>/{ops,service,models,…}.py`; file trong package con bỏ tiền tố.
- Tách là refactor thuần: tên operation, đường dẫn, hành vi giữ nguyên.
- **File test / kịch bản kiểm** (`backend/tests/`, `frontend/test/`, `*.test.*`, `realtime/scripts/smoke_*`, `realtime/test/`): tối đa **~800 dòng** — vượt thì tách theo nhóm luồng, helper dùng chung sang `*_lib`.

**R10 — Mã `loc` của log: cấp liền mạch, kiểm trước khi cấp.**
- Mọi log có `extra={"loc": "<tiền tố><4 số>"}`; tiền tố theo miền (bảng ở [backend/logging §2](.claude/backend/architecture/logging.md)).
- Log mới của một tính năng đã có: lấy số **cao nhất trong khối của tính năng đó** rồi cấp số kế tiếp. Module mới khai tiền tố của mình ở `LOG_PREFIXES`.
- Kiểm trước: `grep -rhoE '"loc": *"<tiền tố>[0-9]+"' backend/app | sort -u`. Test luật bắt trùng hoặc sai tiền tố.

**R11 — Mọi giá trị mặc định / fallback phải quan sát được.** Code dùng mặc định vì thiếu cấu hình thì **không được âm thầm**:
1. Log `INFO` / `WARNING` có `loc`, nêu **giá trị đang hiệu lực** và `DEFAULTS_APPLIED=[…]`.
2. Nơi có trace (agent) thì thêm attribute / event trên span, không chỉ log.
3. Doc thiết kế liệt kê **bảng mặc định**: key → giá trị mặc định → nguồn thật khi được cấu hình.

**R12 — Tính năng tắt theo cờ phải đi qua một chỗ duy nhất, tắt thì no-op.**
- `MONGO_ENABLED=false` → mọi ghi Mongo đi qua sink (`get_sinks()` / `TraceSink`); khi tắt, sink là no-op và cảnh báo **một lần mỗi process** (`obs0001`).
- Nghiệp vụ **không** gọi Mongo trực tiếp. Cờ thêm sau này theo cùng cách: một choke-point, no-op, cảnh báo một lần.

**R13 — Dữ liệu phân loại theo `type` / `kind` dùng Pydantic discriminated union, không dict thô.** Áp cho: span trace theo kind, `action_config` của hook, action của thông báo, bản ghi usage, document event log. Thêm loại mới = thêm class con vào union.

**R14 — Phân trang: `limit` tối đa 100, mặc định 20.** Vượt quá → 422 mã 1002. Frontend lấy danh sách cho dropdown / lookup dùng `limit=100`.

### C. Frontend

**R15 — Đăng nhập ở frontend chỉ dùng JWT Bearer.**
- Không dùng session cookie. Access token + refresh token xoay vòng; mỗi request gắn `Authorization: Bearer`.
- Gặp 401 → refresh **một lần dùng chung** (single-flight) → gọi lại; refresh hỏng → xoá token, về `/login?next=…`.
- Base URL chỉ lấy qua **một** hàm dựng đường dẫn `/bizwithagents/api/…`.

**R16 — Bảng dữ liệu: cột chữ dài cắt ngắn + Tooltip; điện thoại dùng thẻ.**
- Desktop: `max-w-[Npx]` ở cả `<TableHead>` / `<TableCell>`; nội dung bọc `<span className="block truncate">`; hover hiện đủ bằng `<Tooltip>` (Radix) trong `<TooltipProvider delayDuration={300}>`. Không dùng thuộc tính `title`.
- Dưới `md`: danh sách hiện dạng **thẻ**, không bảng cuộn ngang.

**R17 — JSON chỉ đọc hiển thị bằng `<JsonView>`.** Áp cho: span trace, input của event log, mẫu issue, args / kết quả tool, xem trước cấu hình. Giá trị không phải JSON thì hiện nguyên chữ. JSON cần **sửa** thì dùng editor riêng.

**R18 — Realtime-first.**
- Mọi operation ghi khai `invalidates`.
- Thay đổi của người khác, của agent, của scheduler phải tới UI qua socket (`data:changed`, toast, badge); không bắt user tải lại trang.
- Thao tác ghi nghiệp vụ vẫn đi REST (idempotency, lỗi rõ ràng); chiều socket vào chỉ cho thao tác nhẹ.

### D. Agent

**R19 — Observability của agent chỉ đi qua `RunMiddleware` + `Tracer`.**
- Mọi luồng chạy agent / LLM / graph (chat, router, chuyên gia, chạy thử hook, job nền) phải đi qua middleware + tracer. Không tự dựng span / emitter song song.
- Thêm loại span mới = thêm schema vào union span (R13). Ghi qua `TraceSink` (Mongo, theo cờ — R12); usage và chi phí ghi qua tracer.

**R20 — Mọi graph đã compile phải có checkpointer.**
- `compile(checkpointer=get_checkpointer())` cho agent, router, chuyên gia.
- `get_checkpointer()` trả `None` → `WARNING` kèm `DEFAULTS_APPLIED=[checkpointer]` (R11).
- Nguồn sự thật của lịch sử chat là `agent_messages` trong Postgres.

### E. Vận hành và kiểm thử

**R21 — Truy cập DB: ưu tiên MCP.** Chỉ dùng CLI (`psql`, `rabbitmqctl`, `redis-cli`…) khi MCP thiếu chức năng, và nói rõ vì sao. Không đọc / in file secret (`.env`, `.secrets/`, token).

**R22 — Test giao diện (Playwright) giao cho subagent Sonnet 5.5, effort medium** (`model: sonnet`, `effort: medium` — D21). Đây là subagent **duy nhất** được mở (R26). Prompt giao việc phải có:
- yêu cầu rõ: URL, tài khoản, từng bước, kích thước màn hình (375 + 1440);
- Definition of Done đo được (`console error = 0`, không cuộn ngang, …);
- bằng chứng: screenshot, lỗi console / network nguyên văn;
- tên model đã chạy.

Thiếu một mục = chưa xong.

**R23 — Trang doc HTML.** `make docs` sinh `.html` cạnh mỗi `.md` trong `.claude/` + `.claude/index.html` (`scripts/docs_site.py` → package `scripts/docsite/`); sơ đồ archify (`.claude/**/diagrams/*.<loại>.json`) sinh bằng `make diagrams`. Sửa `.md` / `CLAUDE.md` / spec sơ đồ xong chạy lệnh tương ứng và commit cả `.html` + `diagrams.lock.json`; `make docs-check` nằm trong `make ci`.

**R24 — Debug phiên chat bằng một lệnh dump.** `bw dump-chat-session <session_id> [--out file]` gom phiên, tin nhắn, run, duyệt (Postgres), checkpoint LangGraph, span trace (Mongo, nếu bật) vào một file JSON trong `debug/` (đã gitignore). Chưa có `session_id` thì hỏi chủ dự án, không tự đoán.

**R26 — Phiên chính tự làm hết: đọc code, viết code, viết + chạy test (unit, tích hợp, smoke), debug, tra cứu** (D20, D21).
- Không mở subagent (Agent / Explore / Plan / fork / Workflow) — tốn token của chủ dự án — **trừ** test giao diện Playwright (R22: một subagent Sonnet 5.5) hoặc khi chủ dự án yêu cầu.
- Lúc subagent Playwright chạy trên stack thử (`make dev-up`), phiên chính không dừng / dựng lại stack và không chạy test tích hợp dùng chung tài nguyên `*_test`; không commit khi subagent đang sửa file.

**R27 — Deploy = commit + push `main`; Coolify tự kéo về** (mô hình triển khai D19).
- Tính năng xong (test qua, tài liệu đã cập nhật, `make secrets-scan` sạch — D30) thì commit rồi push `main`. Coolify tự deploy qua webhook GitHub App ([deploy](.claude/deploy/CLAUDE.md)).
- Sau push: theo dõi deployment trên Coolify (MCP) tới `finished`, rồi `make smoke-prod URL=<domain của app>`. Hỏng thì đọc log, sửa, push tiếp.
- Uuid app / URL Coolify / token đọc từ `.secrets/coolify.env` — không ghi vào tài liệu. `make deploy` chỉ dùng khi webhook không chạy.

**R28 — Tự chạy theo plan tới 100% tính năng; chỉ gọi chủ dự án khi thật sự cần.**
- Làm lần lượt task trong plan (roadmap → `plans/`), tự quyết, không dừng chờ duyệt. Chỗ plan cần quyết mà chưa có `D<n>` thì tự chọn theo R4 rồi ghi `D<n>` kèm "Claude tự quyết (uỷ quyền R28)".
- Chỉ gọi khi bị chặn bởi việc chỉ chủ dự án làm được: secret / khoá mới, quyền hay thao tác trên dịch vụ ngoài (GitHub, Cloudflare, Google), quyết định không đảo ngược được (xoá dữ liệu thật…). Gọi bằng `scripts/notify.sh "…"` (hoặc `make notify MSG=…`; URL ở `.secrets/discord.env`): việc bị chặn, phương án khuyến nghị + giá từng phương án. Trong lúc chờ thì làm task khác không phụ thuộc.

---

*Cập nhật: 2026-10-15*
