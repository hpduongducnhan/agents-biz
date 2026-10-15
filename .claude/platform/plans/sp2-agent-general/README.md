# SP2 — Agent tổng quát cho mọi tenant

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [roadmap](../../design/roadmap.md) · [template-v1 §3.5](../../design/template-v1.md) · [decisions D22–D23](../../design/decisions/d01-current.md) · [agent-runtime](../../architecture/agent-runtime.md) · [tenancy](../../architecture/tenancy.md)

**Trạng thái:** **Xong** (2026-10-15) — plan dạng đặc tả (D18). Kết quả ở [roadmap](../../design/roadmap.md); E2E: `scripts/e2e/sp2_agent_ui.py` (ảnh + `result.json` ở `.e2e/sp2/`).

## Goal

Module mới cắm vào trợ lý chỉ bằng khai báo (toolset, ngữ cảnh, chuyên gia) mà không sửa lõi agent; mọi dữ liệu hội thoại nằm trong tenant của người chat; superadmin thấy chi phí AI theo từng khách hàng và tắt được trợ lý cho một tenant; trả lời dạng stream như SP17 của dự án nguồn.

## Architecture

**Registry toolset** (`app/agent/config/toolsets.py` — thay hằng `TOOLSETS` / `CONFIRM_WRITES`):

| API | Việc |
|---|---|
| `register_toolset(name, description, *, confirm_writes=(), roles=ALL_ROLES)` | thêm toolset; tự `declare_permissions("agent", {"agent.<name>": …}, roles=…)`; op trong `confirm_writes` mặc định "hỏi duyệt" qua trợ lý |
| `toolsets()` · `toolset_description(name)` · `confirm_writes()` | đọc registry — Studio (`studio.tool_catalog`), seed agent, khối ngữ cảnh "quyền truy cập", `default_policy` |

Nền đăng ký `lookup` (thông báo). Module gọi trong `app/<module>/agent.py`. Test luật: mọi `@operation(agent=True, toolset=X)` có `X` đã đăng ký; toolset đăng ký mà không có op → cảnh báo test.

**Dữ liệu theo tenant** (D22):

| Bảng / nơi ghi | Thay đổi |
|---|---|
| `agent_sessions` · `agent_messages` · `agent_runs` · `agent_approvals` | kế thừa `TenantScoped` (sửa thẳng migration agent — template chưa deploy, DB dev dựng lại) |
| `agent_usage_hourly` | bỏ hẳn (D24 — đã thôi ghi từ SP6 của dự án nguồn); chi phí theo tổ chức đọc `agent_llm_calls` |
| span trace (Mongo) | thêm `tenant_id` cạnh `user_id`; `traces.list` + `usage.summary` / `usage.errors` lọc `tenant_id`, `group_by=tenant` (nhãn = tên tenant) |
| `agent_chat_blocks` · `agent_user_limits` | giữ toàn nền tảng (công cụ superadmin) — lý do đã có ở `PLATFORM` của test B14 |

Đường chạy lượt: task `agent.run_turn` / `resume_turn` / cron dọn lượt treo mở `tenant_session(run.tenant_id)` (đọc run bằng `ALL_TENANTS` một lần để biết tenant); principal agent đã có `tenant_id` → tool đi `run_operation` nên tự scope. Lượt chạy, tin nhắn, duyệt tạo mới tự được gán `tenant_id` (`before_flush`).

**Tắt trợ lý theo tenant:** `tenants.policies.agent_enabled = false` → `agent.send` / `agent.decide_approval(s)` → 403 `6023` "Trợ lý đang tắt cho tổ chức của bạn"; `agent.list_agents` trả rỗng; `auth.me` → `tenant.agent_enabled`; frontend ẩn mục Trợ lý, nút nổi, trang `/assistant` báo tắt. Đổi chính sách → `data:changed` (`auth.me`, `agent.agents`, `agent.chat_limits`, `tenant.current`) tới phòng tenant.

**Ngữ cảnh lõi** (`agent/runtime/context.py`): dòng user (tên, role, **tên tenant**, ngôn ngữ, múi giờ, giờ hiện tại) + dòng quyền truy cập đọc registry toolset; module góp dòng qua `register_context` (đã có ở SP0).

**Agent seed:** orchestrator `assistant` "Assistant" + chuyên gia `general`; module thêm chuyên gia qua `register_specialist` (đã có ở SP0). Persona trung tính (`prompts/persona.md`, viết tiếng Anh, trả lời theo `locale`) — kiểm lại không còn tên / persona của dự án nguồn / ví / nhóm.

**Stream chat** (D23 — chép SP17 của dự án nguồn — D111–D113 bên đó): `system_settings.chat_stream` (mặc định `true`) + `chat_stream_flush_ms` (mặc định theo dự án nguồn); tắt → model `disable_streaming=True`, `stream_mode=["updates"]`, gửi cả câu trong một `agent:token`; `agent/runtime/streaming.py` gom chữ theo cửa sổ; frontend `lib/use-typewriter.ts` hiện đều tay ở màn chat đơn giản (`LiveTurn`), màn gỡ lỗi giữ vẽ thô; trang `/sa/ai-settings` (nhóm Trợ lý AI) gom cài đặt chat từ `/sa/settings` + `/sa/chat-guard` phần mặc định, dùng chung `system.get_settings` / `system.update_settings`.

## Global Constraints

- Không đổi tên op / đường dẫn REST của agent; Studio giữ nguyên hành vi với superadmin.
- Op Studio / trace / usage là `superadmin=True` → không scope (đọc chéo tenant có chủ ý).
- Dữ liệu hội thoại của tenant A không đọc được từ phiên tenant B — kể cả qua `agent.get_session` / `agent.run_events` với id đoán được (→ 404).
- Bảng mặc định R11 cho `chat_stream`, `chat_stream_flush_ms`, `agent_enabled`.

## Tasks

| # | Việc | Kết quả |
|---|---|---|
| T1 | Registry toolset | `register_toolset` + đọc registry ở Studio / seed / ngữ cảnh / policy duyệt; quyền tự khai; test luật toolset; doc agent-runtime |
| T2 | Bảng agent `TenantScoped` | model + migration; task / cron chạy lượt mở `tenant_session`; test tách tenant (phiên, tin nhắn, run_events, duyệt chéo tenant → 404); B14 bỏ 4 bảng khỏi `PLATFORM` |
| T3 | Usage + trace theo tenant | `tenant_id` ở span + `agent_llm_calls` (D24); lọc / gộp `tenant` ở `usage.*`, `traces.list`; UI `/sa/usage` + `/sa/traces` có bộ lọc tổ chức |
| T4 | `agent_enabled` | `6023`, ẩn trợ lý ở frontend, `data:changed` khi đổi; test BE + FE |
| T5 | Ngữ cảnh + persona + seed | dòng tenant trong ngữ cảnh; rà prompt; `make agent-eval` (LLM giả) xanh |
| T6 | Stream chat (D23) | chép SP17 của dự án nguồn: backend (`streaming.py`, runner, llm, settings) + frontend (`use-typewriter`, `LiveTurn`, `/sa/ai-settings`, tách `sa/settings/shared.tsx`) + test |
| T7 | Tài liệu | agent-runtime (registry toolset, tenant, stream, `6023`), tenancy (bảng agent), roadmap |
| T8 | Kiểm + release | `make ci`; smoke-local 2 chế độ Mongo (thêm: tenant tắt trợ lý → `6023`; user tenant khác không đọc được phiên chat → 404); E2E Playwright (subagent — R22) 375 / 1440: chat stream, tắt trợ lý theo tenant, `/sa/ai-settings`, `/sa/usage` lọc tổ chức |

## Definition of Done

- `make ci` xanh; `make dev-up` + `make smoke-local` hai chế độ Mongo xanh.
- Thêm một toolset + chuyên gia mới chỉ cần file `agent.py` của module (kiểm bằng test đăng ký toolset giả trong test).
- E2E: chat có chữ chạy dần; tắt stream vẫn trả lời đủ; tenant tắt trợ lý → không thấy trợ lý; `/sa/usage` gộp theo tổ chức.

## Self-Review

- Hook vòng đời / webhook chạy trong lượt → cùng `tenant_session`; hook là cấu hình toàn nền tảng nên điều kiện hook không lọc theo tenant.
- Cron dọn lượt treo / duyệt hết hạn chạy chéo tenant: session worker không scope (cập nhật theo id) — đúng vì không tạo dòng mới; dòng mới do worker ghi (tin, duyệt) chép `tenant_id` của phiên / lượt.
- Sau E2E: vùng chạm `Switch` ở điện thoại nới thành 48 px (`after:-inset-3.5`); `useTypewriter` mount với lượt đã xong → hiện đủ ngay (trước đó mở lại `/assistant` chạy lại chữ lượt cũ); dòng `none` ở usage theo tổ chức có nhãn "Chưa gắn tổ chức".

---

*Cập nhật: 2026-10-15*
