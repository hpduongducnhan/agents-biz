# Platform — Trợ lý AI: cấu hình, lượt chạy, duyệt, key, hạn mức, trace, hook

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [decisions](../design/decisions/README.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0; SP2: toolset / ngữ cảnh / chuyên gia là registry của module, dữ liệu hội thoại theo tenant — D22, trả lời dạng stream bật / tắt — D23). Code: `backend/app/credentials/`, `backend/app/agent/` (`config/`, `chat/`, `runtime/`, `trace/`, `hooks/`, `guard/`, `router/`, `ops/`, `tasks.py`), `backend/app/observability/traces.py`; giao diện `frontend/src/features/agent/`, `frontend/src/pages/{assistant,studio}/`, `frontend/src/pages/sa/{TracesPage,TraceDetail,UsagePage,ChatGuardPage}.tsx` + `pages/sa/{traces,usage}/`.

## 1. Thành phần

| Thư mục / file | Việc |
|---|---|
| `credentials/` | Bảng `credentials` (bản mã Fernet + `key_id` + `masked_hint`), `seal` / `reveal(purpose)`, `bw credentials new-key\|rotate`, op `credentials.*` (không bao giờ trả giá trị) |
| `agent/config/` | Bảng cấu hình (`0008`): provider, model + giá, agent, pool key, hạn mức (chung / theo user), toolset, override tool, hook, persona · `registry.load` → `AgentSpec` bất biến (cache theo phiên bản `bw:agentcfg:v` + broadcast `agent.config_changed`) · `toolsets.py` (registry `register_toolset`) · seed agent "Trợ lý" · `remote_models.py` (danh sách model phía provider: Gemini / Anthropic / OpenAI / tương thích OpenAI, đi hết trang, key trong header, giá kiểu OpenRouter quy ra mỗi 1M token) |
| `agent/chat/` | Bảng chat (`0005`, `TenantScoped` — D22): `agent_sessions`, `agent_messages` (nguồn sự thật lịch sử), `agent_runs` (một run mở mỗi phiên — partial UNIQUE), `agent_approvals` · `service.py` (cấp `seq` trong khoá dòng phiên) · `approvals.py` |
| `agent/runtime/` | `tools.py` (tool từ `@operation`) · `prompt.py` · `context.py` (khối `<context>`) · `checkpoint.py` (schema `agent_lg`) · `llm.py` · `keys.py` · `limits.py` + `limits.lua` · `middleware.py` (`RunMiddleware`, `KeyRing`, `TokenWatch`) · `streaming.py` (`StreamCfg` — D23) · `runner.py` |
| `agent/trace/` | `events.py` (`RunEmitter` + bộ đệm Redis) · `spans.py` (union span R13) · `tracer.py` (R19 — cả document usage `agent_llm_calls`, SP6) · `noop.py` · `usage.py` (token / chi phí một lần gọi, cộng `agent_runs.cost`) |
| `agent/hooks/` | `schemas.py` (union hành động R13) · `conditions.py` · `engine.py` · `webhook.py` (task taskiq) |
| `agent/router/` | bảng `orchestrator_routes` (`0011`) · `RouteDecision` · prompt router (bảng route + 6 tin gần nhất + ngữ cảnh rút gọn) · `decide` (lọc slug, dự phòng `general`, luật bám) |
| `agent/runtime/{plan,steps}.py` | `Plan{steps, cursor, handoffs, clarify}` lưu `agent_runs.plan` · chạy router → từng bước chuyên gia, `handoff`, resume theo `cursor` |
| `agent/ops/` | `studio.*` (gồm route), `agent.*` (chat + lượt), `traces.*`, `usage.summary` + `usage.errors` |
| `agent/eval.py` | `bw agent-eval` — router trên `tests/agent_eval/intents_vi.yaml` (105 câu), model thật, đạt ≥ 95 % |
| `agent/tasks.py` | `agent.run`, `agent.resume` (lane `agent-run`, retry 0) · `agent.sweep_runs` (mỗi 30 s) · `bw work` có lane `agent-run` nạp sẵn gói provider LLM trước khi nhận task (`llm.warm_providers`, ~2 s lúc khởi động, `agt1001`) — lượt chat đầu sau deploy không chậm thêm ~0,5–1 s |
| `agent/testing/fake_llm.py` | LLM giả kiểu OpenAI cho test / smoke / E2E (`make fake-llm`, cổng 8799 ở stack thử) |

## 2. Một lượt chạy

```
agent.send ──(1 txn)──▶ tin user + run queued ──after commit──▶ agent.run.kiq(run_id)
                                                                   │ lane agent-run
runner.execute: CAS queued→running ─▶ heartbeat 15 s ─▶ before_run hook ─▶ prompt + <context>
   ─▶ KeyRing.model() ─▶ create_agent(model, tools, [RunMiddleware], checkpointer) ─▶ astream
        ├─ chữ  → agent:token (gom chat_stream_flush_ms; tắt stream → cả câu một lần)  ├─ tool → agent:step running → done / error
        ├─ tool confirm → agent_approvals + interrupt → run waiting_approval (checkpoint giữ)
        │        agent.decide_approval → hết yêu cầu chờ → agent.resume → Command(resume)
        └─ hết → ghi tin assistant / tool → run done → agent:end → after_run hook
```

| Trạng thái run | Vào khi | Ra |
|---|---|---|
| `queued` | `agent.send` | `running` (CAS — tối đa một lần), `cancelled` (`agent.cancel`), `failed` 6015 (quá 10 phút chưa chạy) |
| `running` | claim / resume | `done`, `failed` (6011 / 6012 / 6013 / 6019 / 1000), `cancelled` 6014 (cờ `bw:run:<id>:cancel`, kiểm 0,25 s), `waiting_approval`, `failed` 6015 (quá 90 s không heartbeat hoặc process tắt giữa lượt) |
| `waiting_approval` | tool cần duyệt | `running` (resume, mọi yêu cầu đã quyết hoặc hết hạn 24 giờ), `cancelled` |

- **Lịch sử:** ≤ `chat_history_limit` **tin hội thoại** gần nhất trước lượt (tin user + trả lời có chữ; dòng tool không tính), mở đầu bằng tin user; `chat_history_tools` bật → kèm tool call + kết quả nằm giữa, tắt → chỉ chữ. Router đọc `min(12, limit)`, không tool. Tool call chưa có kết quả bị bỏ khi ghi (provider từ chối lịch sử mồ côi).
- **Phiên tự quản:** `agent.send(auto=true)` → server chọn phiên đang mở (`chat.current_session`: phiên mới nhất của user với agent đó, tin cuối trong `chat_session_idle_min` phút hoặc còn lượt mở) hoặc tạo phiên mới; `agent.current_session` trả phiên đang mở + phiên ngay trước cho màn đơn giản.
- **Huỷ:** chữ đang dở được lưu thành tin assistant `status=cancelled`.
- **Checkpoint:** thread = `run_id`, `durability="exit"`; xoá thread khi lượt dừng hẳn (chỉ lượt chờ duyệt giữ).
- **Lỗi lượt** không thành tin nhắn: `agent_runs.error_code / error`, UI đọc `last_run`.

## 3. Sự kiện realtime (tới phòng `user:<id>`)

| Sự kiện | Dữ liệu (ngoài `run_id`, `session_id`, `seq`) |
|---|---|
| `agent:start` | `agent_id` |
| `agent:route` | `steps [{agent_id, slug, name, task}]`, `clarify` |
| `agent:token` | `delta` |
| `agent:step` | `call_id`, `name` (tool), `title` (op), `status` `running\|done\|error`, `args` (đã che) / `preview` (≤ 500) |
| `agent:llm` | (SP7) node `model` vừa trả: `status` `done`, `tools [{name, title}]` (rỗng = soạn trả lời), `text` bool, `ms`, `tokens {input, output}` — phát ở `runner._stream` |
| `agent:approval` | `approval_id`, `call_id`, `name`, `operation`, `title`, `args` (đã che), `expires_at` |
| `agent:approval_decided` | `approval_id`, `call_id`, `status`, `decided_by`, `reason` |
| `agent:end` | `message_id`, `usage`, `status` `done\|cancelled` |
| `agent:error` | `code`, `message` |

Lượt có router: `agent:token` / `agent:step` / `agent:llm` / `agent:approval` mang thêm `by {agent_id, slug, name}` (chuyên gia đang chạy). `seq` tăng dần mỗi run; mọi sự kiện cũng `RPUSH bw:run:<id>:events` (TTL 1 giờ, ≤ 5 000 — quá trần bỏ `agent:token`). Client (`useRunStream`) bỏ `seq` đã thấy, hở `seq` / socket nối lại / mở phiên giữa lượt → `agent.run_events {after_seq}`; bộ đệm hết (`available=false`) → đọc lại phiên.

## 4. Tool từ `@operation`

- **Toolset** khai ở `app/<module>/agent.py` bằng `register_toolset(name, "<việc>: <chi tiết>", confirm_writes=…, roles=…)` (`agent/config/toolsets.py`; nền có `lookup`) → quyền `agent.<name>` tự vào catalog, role có sẵn trong `roles` (mặc định cả ba) nhận quyền, role tự tạo đang có `agent.chat` nhận ở lần migrate đầu. Lõi nạp `agent.py` của mọi miền (`PARTS` ở `app/domains.py`). Test luật: op `agent=True` phải gắn toolset đã đăng ký; op trong `confirm_writes` là op agent của đúng toolset.
- Agent dùng tool = op `agent=True` thuộc **toolset** của agent mà user dùng được: quyền hệ thống của op + quyền `agent.<toolset>`. Tool bị ẩn ghi `input.tools_hidden {tool: lý do}` ở span run / bước chuyên gia. Tool chạy qua `run_operation(..., source="agent", agent_run_id=…)` — cùng kiểm quyền, event log, realtime như web.
- **Principal của lượt chạy** dựng từ DB mỗi lượt: user thường = quyền theo role; **superadmin = `sup=False` + mọi quyền đang dùng** → trợ lý của superadmin chỉ chạm dữ liệu của chính mình (từ SP1: trong tenant của mình); trên web superadmin vẫn vượt mọi kiểm quyền. Miễn hạn mức chat tính theo principal của web (`agent.send`).
- Ngữ cảnh có dòng `agent_access` khi user thiếu `agent.<toolset>` nào → trợ lý nói rõ "chưa được cấp quyền dùng trợ lý cho việc đó".
- Tên tool = tên op đổi `.` → `_` (`notifications.list` → `notifications_list`). Schema: `$defs` inline, bỏ tham số khoá + `idempotency_key`; tham số mặc định hiện `default`.
- **Policy:** `read` / `write` → `auto`; `destructive` **và `confirm_writes`** của toolset (op ghi rủi ro do module khai) → `confirm`; override (Studio) hoặc hook chỉ **nâng** (`confirm` / `deny`); `deny` → không đưa tool vào.
- `idempotency_key` thiếu → `agent-<sha256(run_id:call_id)[:40]>` — chạy lại sau resume không ghi đôi.
- `AppException` → chữ `Lỗi <mã>: <thông điệp> — <data>` trả LLM để tự sửa; lỗi hệ thống → `Lỗi 1000: …` + log `agt0301`; kết quả cắt 20 000 ký tự.

## 5. Duyệt

- Một dòng `agent_approvals` mỗi tool call (UNIQUE `(run_id, tool_call_id)`), hạn 24 giờ. Resume chạy lại tool → lấy lại dòng cũ, quyết định đọc từ DB.
- `agent.decide_approval` (người chat hoặc superadmin; đã quyết / hết hạn → 6008). Hết yêu cầu chờ + run `waiting_approval` → kick `agent.resume` sau commit.
- `agent.decide_approvals {run_id, approval_ids ≤ 50, approve, reason}`: quyết cùng lúc các id còn chờ của lượt trong một transaction; đã quyết / hết hạn / khác lượt → `skipped`; không id nào quyết được → 6008; trả `{decided, skipped, resumed}`.
- Cả hai op (và `agent.cancel`) **khoá dòng `agent_runs` trước** dòng approval → hai lệnh quyết song song xếp hàng, lệnh sau luôn thấy đúng số còn chờ → resume đúng một lần (trước SP10 có thể kẹt `waiting_approval`).
- Tool chạy bằng **tham số đã duyệt** (`APPROVED_ARGS`); khoá lớp hai trong `run_tool`: tool `confirm` không có người duyệt → không chạy.
- Từ chối / hết hạn → LLM nhận "Người dùng đã từ chối…" / "Yêu cầu duyệt đã hết hạn…".
- Checkpointer không dựng được → tool cần duyệt trả lỗi cho LLM (không chạy), `WARNING DEFAULTS_APPLIED=[checkpointer]` (R20).

## 6. Key + xoay vòng

| Bước | Luật |
|---|---|
| Key khoẻ | trong `agent_keys` bật + `credentials.status=active` + không có `bw:key:cool:<id>` |
| Chọn | `round_robin`: `INCR bw:rr:<agent>` mod số key (sắp theo id) · `auto`: ít request nhất (giờ này + giờ trước, `bw:key:req:<id>:<giờ>`) ÷ `weight`, hoà → ngẫu nhiên |
| Lỗi provider **trước** chữ đầu (`TokenWatch`) | `rate` (429) → nguội `key_cooldown_sec` + đổi key · `auth` (401 / 403) → tắt credential + issue + báo superadmin (`agent_key_disabled`) + đổi key · `server` (5xx / mạng / lỗi provider báo giữa luồng sau HTTP 200 — `openai.APIError` không mã, `anthropic.APIStatusError` 2xx, D74) → thử lại 1 lần cùng key rồi đổi · khác → lỗi · lượt hỏng 6011 → log `WARNING` `agt0508` |
| Hết key | lúc bắt đầu → 6010; giữa lượt → lỗi provider gốc → 6011 |
| Sau khi đã có chữ | không thử lại → 6011 |

Key đã dùng ghi `agent_runs.credential_ids`, span llm (`credential_id` + `masked_hint`) và usage.

## 7. Hạn mức theo user + chống spam

- **Hai tầng, kiểm cùng lúc:**
  - **theo agent:** `agent_user_limits` (từng trường) ưu tiên `agent_limits`; NULL = không giới hạn (Studio — giới hạn chi phí theo agent);
  - **theo tài khoản**: cộng chung mọi agent; mặc định hệ thống `chat_per_minute` 10 · `chat_per_hour` 100 · `chat_per_day` 400 (`/sa/chat-guard`) → role (`AccountPolicies`, lấy lớn nhất, `0` = không giới hạn và thắng) → user ghi đè.
  - Superadmin miễn cả hai.
- Lua (`limits.lua`) kiểm **6 khoá** rồi mới cộng — vượt khoá nào thì không cộng khoá nào: `bw:lim:<agent>:<user>:{minute|hour|day}:<mốc>` + `bw:lim:user:<user>:{minute|hour|day}:<mốc>` (mốc theo `APP_TIMEZONE`, TTL 120 s / 2 giờ / 2 ngày). Vượt → 429 **6001** `{window, limit, scope: agent|account, retry_after_sec}`.
- **Tự chặn tạm** (D93, `agent/guard/service.py`): mỗi lần `agent.send` bị 6001 / 6002 là một lần chạm (`bw:chat:strike:<user>`, TTL M phút). Đủ `chat_autoblock_strikes` (5) lần trong `chat_autoblock_window_min` (10) phút → dòng `agent_chat_blocks` (`source=auto`) hạn `chat_autoblock_minutes` (30) × 2^(lần tự chặn trước trong 24 giờ), tối đa 1 440 phút. Ghi bằng session riêng vì op sắp rollback; thông báo `agent_chat_blocked` tới user, `data:changed studio.chat_blocks` tới superadmin, `WARNING agt0901`.
- **Chặn tay**: `studio.block_chat {user_id, minutes | null, reason}` / `studio.unblock_chat` / `studio.list_chat_blocks` (superadmin). Đang bị chặn → `agent.send` trả 403 **6022** `{until, reason, source}`; lượt đang chạy chạy nốt. Không khoá tài khoản.
- `agent.chat_limits` (user): hạn mức tài khoản hiệu lực + số đã dùng trong cửa sổ hiện tại + chặn (nếu có) — màn chat hiện "còn N tin hôm nay" và khung "tạm không dùng được trợ lý tới …".
- Trần token / ngày: `bw:tok:<agent>:<user>:<ngày>` cộng sau mỗi lần gọi LLM; đã chạm → 429 **6002** lúc gửi.
- Insert run lỗi sau khi đã cộng → `refund` (DECR).

## 8. Ngữ cảnh + prompt

- System = persona chung (nếu `persona_shared`) + `instructions` + ghi chú về khối ngữ cảnh — đứng yên để cache; Anthropic gắn `cache_control` ở system + tin cuối lịch sử, OpenAI / Gemini cache theo tiền tố.
- Tin mới = `<context>…</context>` + lời user. Khối ngữ cảnh **không vào lịch sử** DB. Lõi viết: user (id, tên, múi giờ, ngôn ngữ, role, tên tổ chức, superadmin), giờ hiện tại, dòng `agent_access`; module góp dòng qua `register_context(name, fn, order, budget, router)` (`agent/runtime/context.py`) — vượt `budget` thì cắt + "còn N dòng — dùng tool tra cứu", provider lỗi bị bỏ qua + `agt0105`; thêm dòng từ hook `add_context`. Router đọc ngữ cảnh rút gọn = các provider khai `router=True`.

## 9. Trace + usage

- **Tracer** (R19 — chỗ duy nhất dựng span): `run` (id = `run_id`) → `llm` (prompt rút gọn, tham số, token, TTFT, key) → `tool` (con của llm sinh ra call; args / real_args đã che, kết quả ≤ 2 000) → `approval`, `hook`. Span tool / approval id suy từ `call_id` / `approval_id` → resume cập nhật cùng span.
- Ghi nền qua `TraceSink` (R12): Mongo bật → `agent_spans` + `agent_http_raw` (raw HTTP bằng `http_capture`, header / trường bí mật đã che); Mongo tắt → `NoopTracer`, op `traces.*` trả `enabled=false`. Lỗi ghi chỉ log `agt0505`.
- **Usage (giám sát, không tính tiền):** mỗi lần gọi LLM (kể cả lần thử lại / đổi key) `tracer.llm` ghi một document `agent_llm_calls` (Mongo, TTL `span_ttl_days`): user, phiên, agent + `purpose` (`router` / `agent` — `RunMiddleware(purpose=…)`), model, provider, key, `status` + `error_kind` (`keys.classify`: rate / auth / server / other; huỷ không tính lỗi), `error` đã che, `latency_ms`, `ttft_ms`, token (`input_tokens` không gồm cache), `cost` = `(input·p_in + output·p_out + cache_read·p_cr + cache_write·p_cw) / 1e6` USD theo giá model lúc gọi. Document mang `tenant_id` (D22). `agent_runs.cost` vẫn cộng (hook `after_run`). `usage.summary` gộp bằng aggregation (`group_by` provider / model / agent / purpose / **tenant** (nhãn = tên tổ chức; document không có tenant → `none`) / user / key / session / day / hour theo `APP_TIMEZONE`; lọc chéo; ≤ 400 ngày, mặc định 30; tên tra Postgres, giá model kèm dòng); `usage.errors` = lần gọi lỗi gần nhất. Mongo tắt → `enabled=false`.
- **Span:** mọi span mang `user_id` + `tenant_id`. Span `run` thêm `agents` (slug theo bước), `models`, `cost`, `llm_errors`, `input.stream` (`on`, `flush_ms`, `defaults_applied`); resume gộp với giá trị đã ghi. `traces.list` lọc thêm `tenant_id` / `has_error` / `model`, trả `names` (`user:` / `agent:` / `tenant:`).

## 10. Hook vòng đời

| Điểm | Dữ liệu điều kiện | Hành động |
|---|---|---|
| `before_run` | `user.*`, `agent.{id,slug}`, `message.text`, `session.id` | `block` (run `failed` 6019 với lời nhắn, không gọi LLM), `add_context`, `notify`, `webhook` |
| `before_tool` | + `tool.{name,operation,toolset,effect}`, `args.*` | `block` (LLM nhận lời nhắn), `require_approval`, `notify`, `webhook` |
| `after_tool` | + `result.{ok,error_code,text}` | `notify`, `webhook` |
| `after_run` | `user.*`, `agent.*`, `run.{id,status,tokens,cost,tools[]}` | `notify`, `webhook` |

- Điều kiện `{path, op, value}` AND (≤ 10), `op` ∈ `eq ne in contains exists gt gte lt lte` (so số bằng Decimal); `{{path}}` trong chữ. Chạy theo `position`, `block` đầu tiên thắng. Hook hỏng → span lỗi + log `agt0704`, không làm hỏng lượt.
- `notify` → thông báo `agent_hook` (user đang chat hoặc superadmin). `webhook` → task `agent.hook_webhook`: POST JSON, ký `X-BizWithAgents-Signature: sha256=<hmac>` khi có credential, timeout 10 s, kết quả vào event log (`agent.hook_webhook`, lỗi = 6018).
- `studio.test_hook` (POST, không ghi): chạy trên dữ liệu mẫu, `notify` / `webhook` chỉ trả việc sẽ làm (request đã ký).

## 10b. Router + chuyên gia (SP3b)

- **"Assistant" là orchestrator** (`kind=orchestrator`, không toolset): mỗi lượt chạy router trước. Agent `kind=specialist` làm entry → chạy thẳng (không router).
- **Router** = `create_agent(model orchestrator, tools=[], response_format=ToolStrategy(RouteDecision))` qua `RunMiddleware` + `Tracer` (span `router`): đầu ra `{steps: [{agent, task}] 0–3, clarify}`. Slug lạ bị bỏ; không bước + không hỏi lại / lỗi → `general` (`WARNING agt0801 / agt0802 DEFAULTS_APPLIED=[route]`, `fallback` trên span). **Luật bám:** tin assistant cuối của phiên kết thúc bằng "?" + router chỉ ra `general` → giữ chuyên gia lượt trước. `clarify` → orchestrator trả lời thẳng câu hỏi lại (tin `kind=clarify`), không gọi chuyên gia.
- **Chạy bước** (`runtime/steps.py`): mỗi bước dựng `RunContext` của chuyên gia (model / toolset / hook / key ring riêng; `entry_id` = orchestrator → hạn mức + token tính ở entry), thread checkpoint `<run_id>:<i>`, tin nhắn của bước lưu ngay dưới `agent_id` chuyên gia. Tin user của bước có `<task>` (việc router giao) + `<scope>` khi lượt ≥ 2 bước (chỉ làm đúng `<task>`, không làm thay bước khác, việc đã có trong `<earlier>` thì không làm lại — luật nằm trong code, áp ngay cho agent đã seed) + `<earlier>` (chữ + kết quả tool rút gọn của các bước trước trong lượt). Không có bước tổng hợp.
- **`handoff(to, reason)`**: tool có ở chuyên gia khi entry là orchestrator (`return_direct`) — kết thúc bước, chèn bước `to` (task = `reason`) ngay sau; ≤ 2 / lượt. Hết lượt chuyển → **không đưa tool** (tool `return_direct` bị từ chối thì bước dừng ngay sau lỗi, người dùng không có câu trả lời — lỗi gặp trên prod 2026-10-13); không chuyển ngược về chuyên gia vừa chuyển sang mình (`came_from` — chặn vòng A → B → A).
- **Luôn có câu trả lời:** lượt xong mà không bước nào có chữ → câu dự phòng (`kind=fallback`, `WARNING agt0104 DEFAULTS_APPLIED=[reply=fallback]`).
- **Resume:** chờ duyệt ở bước i → `plan` lưu `cursor = i`; `agent.resume` chạy tiếp bước i từ checkpoint rồi các bước sau. Lượt dừng hẳn → xoá thread `<run_id>` + `<run_id>:<i>`.
- **Seed** (`agent.seed`): chuyên gia lấy từ registry `register_specialist(SpecialistSeed(...))` (`agent/config/seed_data.py`; nền có `general` toolset `lookup`, module thêm chuyên gia của mình) — chỉ superadmin chat thẳng (`visible_to=roles`, `[]`), route mặc định (ý định + ví dụ) từ "Assistant"; chuyên gia mới chép model + pool key của "Assistant"; seed còn đúng bản cũ (`previous_toolsets` / `previous_instructions` / `previous_routes` của seed) thì nâng, đã sửa ở Studio thì giữ. Prompt: `prompts/{router,general}.md` + `_common.md`, chuyên gia module ở `prompt_dir` của nó. Persona chung `prompts/persona.md` (trung tính, trả lời theo ngôn ngữ của user) chép vào `agent_system_prompts` lúc seed; DB còn đúng bản cũ (`PREVIOUS_PERSONA`) thì seed nâng (`agt0007`).
- **Trace:** `run → router → llm` · `run → agent:<slug> (task) → llm → tool → approval`. Span `router` / `agent` thêm vào union (R13).

## 11. Mã lỗi + log

- 6001–6023 (`agent/errors.py`; 6016 thuộc `credentials`; 6020 = key khác provider của model; 6021 = quá số lần handoff; 6022 = đang bị chặn dùng trợ lý; 6023 = tổ chức tắt trợ lý). Bảng tiếng Việt ở `frontend/src/lib/i18n/dict/agentUi.ts`.
- `loc`: `agt00xx` cấu hình (`agt0004` thử provider lỗi · `agt0005` lấy danh sách model lỗi) · `agt01xx` lượt / dọn · `agt02xx` sự kiện · `agt03xx` tool · `agt04xx` checkpointer · `agt05xx` runner / provider / usage / trace · `agt06xx` key · `agt07xx` hook / webhook · `agt08xx` router · `agt09xx` chặn chat · `agt10xx` nạp sẵn provider · `cred00xx` credential.

## 12. Bảng mặc định (R11)

| Khoá | Mặc định | Nguồn khi cấu hình |
|---|---|---|
| `CREDENTIAL_KEYS` | dev / test: sinh tạm + `cred0001`; prod bắt buộc (thiếu → 6016) | env Coolify |
| `recursion_limit` / `timeout_sec` | 25 / 90 | cột `agents` (Studio) |
| `chat_session_idle_min` / `chat_history_limit` / `chat_history_tools` | 30 / 20 / bật (`sys0701` `DEFAULTS_APPLIED`) | cài đặt hệ thống (`/sa/ai-settings`); cột `agents.history_limit` cũ không đọc |
| `chat_stream` / `chat_stream_flush_ms` | bật / 50 ms (20–1 000); đọc lỗi → mặc định + `agt0509`, span `run.input.stream.defaults_applied` | cài đặt hệ thống (`/sa/ai-settings` — D23); tắt = gọi mô hình một lần, một `agent:token` mỗi lần gọi |
| `agent_enabled` (tenant) | chưa đặt = bật | `tenants.policies` (`/sa/tenants`); tắt → `agent.send` / duyệt 6023, `agent.list_agents` rỗng, frontend ẩn trợ lý (superadmin không bị chặn) |
| `key_strategy` / `key_cooldown_sec` | `round_robin` / 300 | cột `agents` |
| hạn mức theo agent | không giới hạn | `agent_limits`, `agent_user_limits` (Studio) |
| hạn mức theo tài khoản | 10 / phút · 100 / giờ · 400 / ngày | `system_settings.chat_per_*` (`/sa/chat-guard`), role / user `AccountPolicies` |
| tự chặn | bật · 5 lần / 10 phút → 30 phút (nhân đôi khi tái phạm, ≤ 24 giờ) | `system_settings.chat_autoblock*` (`/sa/chat-guard`) |
| checkpointer | `AsyncPostgresSaver` schema `agent_lg`; lỗi → không chạy tool cần duyệt + `DEFAULTS_APPLIED=[checkpointer]` (`agt0401`) | — |
| trace | Mongo tắt → `NoopTracer` (cảnh báo `obs0001` một lần) | `MONGO_ENABLED` |
| TTL span / raw HTTP | 90 ngày / 7 ngày (đọc cài đặt lỗi → mặc định + `agt0507`) | cài đặt `span_ttl_days` / `raw_http_ttl_days` (`/sa/settings`) |
| bộ đệm sự kiện | 1 giờ, ≤ 5 000 | code (`events.py`) |
| dọn run | `running` > 90 s không heartbeat, `queued` > 10 phút → 6015; duyệt > 24 giờ → `expired` | code (`tasks.py`) |
| model "Assistant" | chưa có → 6009, Studio cảnh báo `no_model` / `no_key` | `scripts/seed_agent.py` / Studio |
| router lỗi / không quyết định | → `general` (`agt0801`, `agt0802`) | — |
| handoff mỗi lượt | tối đa 2 (`MAX_HANDOFFS`) | code (`plan.py`) |

## 13. Giao diện

- `/assistant` **Đơn giản** (mọi user; ẩn khi thiếu `agent.chat` hoặc tổ chức tắt trợ lý — `canUseAssistant`): chữ trả lời hiện đều tay (`lib/use-typewriter.ts`, trễ ≤ 0,6 s; `prefers-reduced-motion` → hiện ngay); không danh sách phiên / chọn agent / JSON; phiên trước (mờ) + vạch "Cuộc trò chuyện mới" + phiên đang mở; mỗi lượt một hàng chấm (`RunDots` — store `LiveRun.trail` từ `agent:route` / `agent:llm` / `agent:step` / `agent:approval` / `agent:error`; lịch sử: `trail.dotsOf` + `get_session.tool_titles`) — hover / chạm xem AI đã làm gì + ổn / không ổn; thẻ duyệt (1 yêu cầu → thẻ đầy đủ; ≥ 2 → thẻ gom `ApprovalGroup` có Duyệt / Từ chối tất cả); nút "Cuộc trò chuyện mới" cạnh ô nhập.
- `/assistant` **Gỡ lỗi** (superadmin, công tắc `?view=debug` / `localStorage` `bw.assistant.view` — chuyển sang mở đúng phiên đang xem): danh sách phiên (sheet ở điện thoại), khung chat stream — mỗi chuyên gia một khối có nhãn + dải "chuyển lần lượt", bước tool gập / mở (JsonView — R17; lịch sử mở lại được tham số + kết quả), thẻ duyệt (Từ chối bắt buộc lý do; ≥ 2 yêu cầu trong một khối → thẻ gom + Duyệt / Từ chối tất cả; đang gửi thì khoá mọi nút duyệt của lượt), nút Dừng, câu mở đầu; trả lời của trợ lý hiện bằng `Markdown` tự dựng React node (không HTML thô).
- `/studio` (superadmin): nút "Gắn model + key cho mọi agent" (`studio.configure_all` — bật trợ lý lần đầu); tab Agent (cơ bản + loại agent, route của orchestrator, pool key, hạn mức, toolset + chính sách từng tool, hook + chạy thử), Provider (+ thử, **Chọn model**), Key (chỉ `masked_hint`), Model + giá (**Thêm từ provider** hoặc nhập tay), Persona. Chọn model: `studio.provider_models` (GET — key tự chọn: key gắn provider rồi key chưa gắn; lỗi provider → 6011 kèm `{status, detail}`, không key → 6010) → tìm / lọc model chat / tick nhiều → `studio.add_models` (≤ 100 / lần, model đã có bỏ qua; giá provider không trả thì 0).
- `/sa/ai-settings` (superadmin — D23): thẻ Trợ lý chat (thời gian chờ phiên, số tin lịch sử, kèm tool) + thẻ Trả lời dạng stream (công tắc + cửa sổ gom chữ), dùng chung `system.get_settings` / `system.update_settings`; `/sa/settings` có link sang.
- `/sa/traces` (SP6: bộ lọc trên URL — tổ chức, user, phiên, agent, trạng thái, model, ngày, có lỗi; mỗi lượt: chuỗi chuyên gia, model, token, chi phí, lỗi LLM, lọc nhanh user / phiên), `/sa/traces/:id` (cây span + chi tiết + raw HTTP), `/sa/usage` (SP6: bộ lọc trên URL — gồm tổ chức, tab gộp **Tổ chức**, 6 thẻ, biểu đồ cột SVG theo ngày / giờ, phân tích theo tab bấm dòng để lọc sâu, lỗi LLM gần đây).

---

*Cập nhật: 2026-10-15*
