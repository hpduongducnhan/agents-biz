# BizWithAgents — Thiết kế template v1

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [decisions](./decisions/README.md) · [roadmap](./roadmap.md) · nguồn tham chiếu duy nhất: dự án nguồn (CLAUDE.md, `.claude/`, code)

**Trạng thái:** ĐÃ CHỐT (2026-10-14) — chủ dự án duyệt bản 2 (tenant đơn giản, agent một bộ dùng chung). Quyết định D1–D16 ở [decisions](./decisions/README.md). **Thứ tự thi công ở §4 đã được thay bằng D17** — trạng thái thật xem [roadmap](./roadmap.md).

---

## 0. Mục tiêu và tiêu chí thành công

**Sản phẩm:** một template fullstack có sẵn trợ lý AI. Mỗi app mới (quản lý dự án, việc cá nhân, học tiếng Anh, học system design…) = **copy template → đổi tên → thêm module nghiệp vụ**. Phần nền không phải viết lại: đăng nhập, phân quyền, tenant, realtime, thông báo, quan sát, agent, PWA, deploy, tài liệu + rule.

**Tiêu chí thành công (đo được):**

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| 1 | App mới từ template chạy được trong ≤ 1 giờ | `make new-app` vào thư mục tạm → `make ci` xanh → `make dev-up` + `make smoke-local` xanh ở cả hai chế độ Mongo |
| 2 | Module nghiệp vụ mới chạy được đầu-cuối trong ≤ 1 buổi | `make new-module NAME=notes` → CRUD web + realtime + tool cho agent + test, `make ci` xanh mà chưa sửa tay dòng nào |
| 3 | Module mẫu Tasks làm được mọi việc bằng web **và** bằng chat | E2E: tạo / sửa / giao / bình luận / xoá (có duyệt) qua chat; người khác cùng tenant thấy ngay, không tải lại trang |
| 4 | Dữ liệu các khách hàng tách hẳn nhau | test: user tenant B đọc / sửa / xoá / gọi tool trên dữ liệu tenant A → 404, kể cả qua agent; scaffold sinh sẵn test này cho mọi module |
| 5 | Đăng nhập + phân quyền đủ dùng thật | email + mật khẩu (xác thực email, quên mật khẩu), Google, lời mời vào tenant; quyền kiểm giống hệt nhau trên web và khi agent gọi tool |
| 6 | Dùng tốt trên điện thoại | 375 / 768 / 1024 / 1440 không cuộn ngang, vi / en đủ khoá, PWA cài được, Web Push |
| 7 | Chất lượng giữ mức dự án nguồn | độ phủ BE ≥ 90 %, FE ≥ 80 %, RT ≥ 90 %; test luật xanh; `grep -riE '<tên nguồn>\|wallet'` trong code = 0 |

**Ngoài phạm vi v1:** app native (PWA là đủ), thanh toán, một user ở nhiều tenant, cấu hình agent riêng từng tenant, SSO doanh nghiệp, billing.

## 1. Lựa chọn chủ dự án đã chốt (2026-10-14)

| # | Câu hỏi | Chốt | Ghi thành |
|---|---|---|---|
| Q1 | Hình thức | Template + module mẫu + công cụ tạo module; app mới = copy + đổi tên | D1 |
| Q2 | Stack | Giữ nguyên dự án nguồn: Python 3.13 FastAPI + FastStream / taskiq trên RabbitMQ · Node Socket.IO · React 19 + Vite · Postgres + Redis (+ Mongo theo cờ) · LangChain v1 / LangGraph · Coolify | D2 |
| Q3 | Tenant | **Đơn giản**: tenant chỉ để tách dữ liệu khách hàng; agent một bộ như dự án nguồn, dùng cho tenant nào cũng được (chủ dự án chỉnh lại, thay câu trả lời "workspace nhiều role" lúc đầu) | D3 |
| Q4 | Mobile | Web ưu tiên điện thoại + PWA, không native | D4 |
| Q5 | Đăng nhập | Email + mật khẩu, Google, mời vào tenant | D5 |
| Q6 | Tài liệu | Mang sang đầy đủ hệ thống rule / D<n> / SP / HLD / `make docs` của dự án nguồn, bỏ nội dung riêng của dự án nguồn | D6 |
| Q7 | Ngôn ngữ | Đa ngôn ngữ, mặc định `vi`, có `en`; agent trả lời theo ngôn ngữ của user | D7 |
| Q8 | Module mẫu | Quản lý công việc (Tasks) | D8 |

## 2. Giữ / sửa / bỏ từ dự án nguồn

Số dòng đo ngày 2026-10-14 (chỉ code, không tính test).

### 2.1 Backend (`backend/app/`)

| Miền nguồn | Dòng | Cách lấy | Ghi chú |
|---|---|---|---|
| `core/` (settings, connections, logging, messaging, operations, security, errors, response, migrate, text) | 3 765 | **Chép nguyên**, đổi tiền tố | thêm bộ lọc tenant ở session (§3.2) — chỗ duy nhất của lõi biết tenant |
| `auth/` | 2 090 | Chép + **thêm** | `users.tenant_id`, claim `tid`; xác thực email, quên mật khẩu, lời mời, chế độ đăng ký (§3.2, §3.3); `seed.py` bỏ ví mẫu |
| `agent/` | 7 911 | Chép + **tổng quát hoá** | toolset / ngữ cảnh / chuyên gia thành registry (§3.5); viết lại prompt; cấu hình agent vẫn toàn nền tảng |
| `credentials/` · `observability/` · `system/` · `devtools/` | 2 019 | **Chép nguyên** | event log thêm `tenant_id`; system settings bỏ `max_backdate_days` |
| `notifications/` (inbox + Web Push) | 895 | **Chép nguyên** | bỏ các kind của ví / nhóm |
| `groups/` | 2 177 | **Bỏ** | nền không có "nhóm"; nhóm nhỏ trong tenant (dự án, lớp học…) là việc của module (§3.2) |
| `wallet/` · `split/` · `drive/` | 9 192 | **Bỏ** | nghiệp vụ riêng của dự án nguồn |
| `tenants/` | — | **Viết mới**, nhỏ (~600 dòng) | bảng, op tenant admin + superadmin, khoá tenant (§3.2) |
| `mail/` | — | **Viết mới** | §3.3 |
| `tasks/` | — | **Viết mới** | module mẫu §3.6 |

### 2.2 Realtime, frontend, deploy, tài liệu, test

| Phần | Cách lấy | Ghi chú |
|---|---|---|
| `realtime/` (Node + Socket.IO) | Chép + **thêm phòng `tenant:<tid>`** (~30 dòng) | §3.2 |
| `frontend/src/lib` (api client + refresh, auth, i18n, realtime, query), `ui/` (UI kit, `JsonView`, `Markdown`, `Table`…) | **Chép nguyên** | bỏ `money`, `owner`, `wallet-catalog`, `split-shares`, `currencies`, `group-perms` |
| `layout/` (AppShell, Header, NavDrawer, MobileDock, InstallGuide, SocketDot) | Chép + **mở slot** | menu, "Thêm nhanh", widget Tổng quan do module đăng ký (§3.4); Header hiện tên tenant |
| Trang auth / profile / notifications / admin / sa / settings / assistant / studio | **Chép nguyên** | ~7 400 dòng; `/admin/users` tự chỉ thấy user cùng tenant |
| Trang "Tổ chức" (tenant admin) + `/sa/tenants` (superadmin) | **Viết mới** | thông tin, thành viên, lời mời · danh sách tenant, khoá / mở, chính sách, chi phí AI |
| Trang wallets / record / recurring / reports / slips / groups | **Bỏ** | |
| `deploy/`, `compose.yml`, Dockerfile, nginx, `scripts/dev_stack.sh`, smoke, `deploy.sh`, `notify.sh` | Chép + **tham số hoá** | tên / cổng / domain qua script đổi tên (§3.1) |
| `CLAUDE.md`, `.claude/`, `scripts/docs_site.py` + `docsite/`, `check_md.py`, sơ đồ archify | Chép + **viết lại nội dung** | §3.9 |
| Test BE (255 file) / FE (96 file) / RT / E2E | Chép phần nền + sửa; bỏ test ví / nhóm / chia tiền | test luật giữ nguyên, thêm luật tenant |

**Đã cân nhắc — cách dựng repo:**

| Phương án | Lịch sử git | Rủi ro sót code nguồn | Công sức |
|---|---|---|---|
| **Repo mới, chép có chọn lọc** | sạch | thấp (kiểm bằng grep ở DoD) | vừa |
| Fork dự án nguồn rồi xoá phần ví | kéo theo ~100 commit ví | cao (migration, seed, prompt, i18n còn sót) | thấp lúc đầu, cao lúc dọn |

→ Chọn **repo mới, chép có chọn lọc**: lịch sử sạch, chuỗi migration bắt đầu lại từ `0001`.

## 3. Kiến trúc — những chỗ khác dự án nguồn

### 3.1 Tên app và cách đổi tên (D9)

Dự án nguồn gắn cứng tên ở nhiều chỗ: CLI `mp`, Redis `mp:`, exchange `mp.*`, đường dẫn `/<nguồn>/api`, service `<nguồn>-*`, cổng 81xx / 168xx.

| Phương án | Code còn đọc thẳng được (grep tên thật) | Chỗ phải sửa khi tạo app | Rủi ro hai app dùng chung Redis / RabbitMQ đụng nhau | Công cụ thêm |
|---|---|---|---|---|
| **Tên cố định trong template + `make new-app` đổi tên một lần** | ✓ | 0 (script làm) | ✗ (script đổi tiền tố) | 1 script Python |
| Tên đọc từ env lúc chạy (`APP_SLUG`, `APP_PREFIX`) | ✗ (chuỗi ghép động) | env + nginx + build FE | ✗ | không |
| Cookiecutter / copier | ✓ | 0 | ✗ | thêm dependency, template khó chạy thẳng |

→ Chọn **tên cố định + script đổi tên**: template tự chạy được như một app thật (để test), code giữ chuỗi literal như dự án nguồn.
- Tên trong template: hiển thị `BizWithAgents` · slug `bizwithagents` (DB, vhost, đường dẫn `/bizwithagents/api`, `/bizwithagents/ws`) · tiền tố `bw` (CLI `bw`, Redis `bw:`, exchange `bw.*`, service `bw-api`…) · cổng local 8201–8204, container 16811–16813.
- `make new-app NAME="Task Hub" SLUG=taskhub PREFIX=th DEST=../taskhub [PORTS=83]` → chép repo (bỏ `.git`, `.env`, `.secrets`, `debug/`, cache), thay tên ở mọi file, đổi tên file / thư mục, `git init`, in checklist việc chủ dự án (env, OAuth, Coolify).
- Kiểm: `make new-app-check` sinh app vào thư mục tạm rồi chạy `make ci` ở đó.

### 3.2 Tenant — tách dữ liệu khách hàng, agent dùng chung (D3, D10–D13)

**Nguyên tắc:** tenant chỉ là **ranh giới dữ liệu**. RBAC, agent, Studio, thông báo, realtime giữ nguyên cách dự án nguồn; lõi thêm **một** bộ lọc `tenant_id` tự động. Code module và agent **không phải nghĩ tới tenant**.

**Mô hình (D10):**

| Phương án | User thuộc | Tool của agent phải nhận tham số tenant | Bộ chuyển tenant ở UI | Một email ở 2 khách hàng | Độ phức tạp |
|---|---|---|---|---|---|
| **Mỗi user thuộc đúng 1 tenant** (`users.tenant_id`, claim `tid` trong JWT) | 1 | ✗ (lấy từ người đang chat) | ✗ | ✗ (dùng email khác) | thấp |
| User thuộc nhiều tenant, role theo từng tenant | n | ✓ | ✓ | ✓ | cao |

→ Chọn **1 user = 1 tenant**: agent chạy y hệt dự án nguồn, chỉ khác là mọi thứ nó đọc / ghi tự nằm trong tenant của người đang chat.
- Bảng `tenants` (`id`, `name`, `slug`, `status` `active | suspended`, `policies` jsonb, `created_at`). Tenant `default` tạo lúc `mp migrate`.
- `users.tenant_id` NOT NULL. Mọi bảng nghiệp vụ của module có `tenant_id` NOT NULL + index (mixin `TenantScoped`).
- Bảng toàn nền tảng (không có `tenant_id`): cấu hình agent (provider, model, key, agent, chuyên gia, hook, persona), credential, permission, role, system settings.

**Tách dữ liệu (D11):**

| Phương án | Module phải tự lọc | Quên lọc thì | Đổi migration | Superadmin xem chéo tenant | Gỡ lỗi |
|---|---|---|---|---|---|
| **Lọc tự động ở session** (SQLAlchemy `do_orm_execute` + `with_loader_criteria` cho mọi model `TenantScoped`; `before_flush` tự gán / kiểm `tenant_id`) | ✗ | vẫn được lọc | ✗ | `ctx.cross_tenant()` tường minh, chỉ superadmin, có log | dễ (một chỗ trong lõi) |
| Tự thêm `where tenant_id = …` ở từng query | ✓ | lộ dữ liệu khách khác | ✗ | dễ | dễ |
| Postgres RLS | ✗ | DB chặn | ✓ (mỗi bảng một policy) | cần role bypass | khó |
| Schema / DB riêng mỗi tenant | ✗ | — | ✓ × số tenant | khó | khó |

→ Chọn **lọc tự động ở session**: an toàn gần bằng RLS mà không thêm gì vào migration, một choke-point (tinh thần R12).
- Runner của `@operation` mở session với `session.info["tenant_id"] = principal.tenant_id` → mọi `select` / `update` / `delete` ORM trên model `TenantScoped` tự có điều kiện tenant; đối tượng mới tự gán `tenant_id`; ghi đối tượng của tenant khác → lỗi.
- Task / consumer nền: message mang `tenant_id`, mở session bằng `tenant_session(tid)`. Cron chạy cho mọi tenant thì lặp từng tenant tường minh.
- Không lọc được SQL thô (`text()`, bảng Core) → test luật cấm SQL thô trên bảng `TenantScoped` trong module (ngoại lệ ghi lý do).
- Test luật: model trong module phải kế thừa `TenantScoped` (ngoại lệ ghi lý do). Redis key chứa dữ liệu tenant phải mang `tid` (`rkey("tasks", tid, …)`).

**Đăng ký và tenant (D12)** — cài đặt hệ thống `signup_mode` (thay `signup_open` của dự án nguồn):

| `signup_mode` | Người đăng ký mới | Hợp với |
|---|---|---|
| **`default_tenant`** (mặc định) | vào tenant `default`, role `member` | app nội bộ / một khách hàng — chạy y như dự án nguồn |
| `new_tenant` | tạo tenant mới, người đăng ký là `admin` của tenant đó | SaaS tự phục vụ; app cá nhân (mỗi người một tenant) |
| `invite_only` | không tự đăng ký được | B2B: superadmin tạo tenant rồi mời admin đầu tiên |

Lời mời chạy ở mọi chế độ: admin tenant mời theo **email** (gửi mail §3.3) hoặc **link** (có hạn + giới hạn số lần dùng, gửi qua Zalo / Slack). Người nhận đăng ký → vào đúng tenant với đúng role. Email đã có tài khoản ở tenant khác → lỗi rõ ràng (2xxx), không gộp.

**Quyền** — giữ nguyên RBAC của dự án nguồn (catalog quyền, role, `user_roles`, `policies` theo role / user, superadmin từ env):

| Role | Phạm vi | Quyền |
|---|---|---|
| `superadmin` (env) | toàn nền tảng | mọi thứ: tenant, Studio, trace, usage, cài đặt hệ thống, role |
| `admin` | trong tenant của mình | `user.view`, `user.manage`, `tenant.settings`, `tenant.invite`, `agent.chat` + mọi quyền module |
| `member` | trong tenant của mình | `agent.chat` + quyền module mặc định cho member |
| `viewer` | trong tenant của mình | quyền xem của module |

- Định nghĩa role **dùng chung** mọi tenant; gán role thì theo user (user chỉ ở một tenant nên gán là trong tenant đó). Role tự tạo: chỉ superadmin (`role.manage`), vì role dùng chung.
- **Đã cân nhắc:** mỗi tenant tự tạo role riêng (`roles.tenant_id`) — thêm một tầng cho thứ v1 chưa cần; để TẦM NHÌN.
- Module khai quyền vào catalog kèm role nhận sẵn: `register_permissions("tasks", {...}, roles={"admin": ALL, "member": {"tasks.view", "tasks.edit"}, "viewer": {"tasks.view"}})`; `@operation(permission="tasks.edit")` như dự án nguồn — không có `group_permission`, không owner resolver.
- `AccountPolicies` (SP9 của dự án nguồn) thêm tầng tenant: mặc định hệ thống → **tenant** → role lớn nhất → user ghi đè. Khoá mới: `user_limit` (số user tối đa của tenant), `agent_enabled`.

**Khoá tenant:** superadmin `tenants.suspend` → dấu Redis `bw:tenant:disabled:<tid>` → REST 403 (2xxx), `rt:revoke` phòng tenant, frontend đăng xuất — dùng lại nguyên cơ chế khoá tài khoản của dự án nguồn.

**Realtime (D13):**

| Phương án | Sửa service realtime | Message mỗi lần ghi | Phải tra danh sách user | Join / leave khi đổi thành viên |
|---|---|---|---|---|
| **Phòng `tenant:<tid>`, join lúc bắt tay theo claim `tid`** | ~30 dòng (một phòng + routing key `tenant.<tid>`) | 1 | ✗ | ✗ (user không đổi tenant) |
| Gửi tới `user:<id>` từng người (dự án nguồn) | 0 | N | ✓ | ✗ |

→ Chọn **phòng tenant**: `ctx.invalidate(keys, tenant=True)`. `data:changed` chỉ mang query key, client tự tải lại theo quyền của mình nên phát cho cả tenant không lộ dữ liệu. Sự kiện riêng (thông báo, `agent:*`, `core:rbac_updated`) vẫn tới `user:<id>`.

**Giao diện:** không có bộ chuyển tenant; Header hiện tên tenant. Admin tenant có trang **Tổ chức** (thông tin, thành viên, lời mời; ẩn mục thành viên khi `user_limit = 1` — app cá nhân). Superadmin có `/sa/tenants`.

**Nhóm nhỏ trong tenant** (dự án, lớp học, phòng ban): nền không có, module tự làm khi cần (vd module Projects có `project_members` + kiểm trong handler). **Đã cân nhắc:** chép "nhóm" của dự án nguồn làm tầng thứ hai trong tenant — bỏ vì đi ngược yêu cầu đơn giản, và phần lớn app không cần.

### 3.3 Mail + luồng đăng nhập mới (D14)

Dự án nguồn không gửi email. Template cần email cho xác thực, quên mật khẩu, lời mời.

| Phương án | Dependency mới | Chạy local không cần tài khoản | Nhà cung cấp dùng được | Hợp B8 (HTTP ra chỉ qua httpx2) |
|---|---|---|---|---|
| **Interface + `console` (dev) + `smtp`** | `aiosmtplib`, `jinja2` | ✓ (`console` ghi log + trang `/sa/mail` xem thư đã gửi ở dev) | mọi nơi có SMTP: Gmail app password, Brevo, SES, Resend SMTP | ✓ (không gọi HTTP) |
| Chỉ HTTP API (Resend / Brevo) | `jinja2` | ✗ | một nhà | ✓ |

→ Chọn **`console` + `smtp`**; HTTP API thêm sau nếu cần (một class transport).
- Gửi bằng task `mail.send` (lane `default`, retry 2, idempotent theo khoá `bw:mail:sent:<id>`); mẫu thư Jinja2 theo `users.locale` (vi / en), có HTML + text.
- Thư: xác thực email (hạn 24 giờ), đặt lại mật khẩu (1 giờ, dùng một lần, thu hồi mọi refresh token khi đổi), lời mời vào tenant (7 ngày).
- Cài đặt `email_verification`: `off` · **`soft`** (mặc định — đăng nhập được, banner nhắc, chưa xác thực thì không mời được người khác) · `required`.
- Google OAuth: chép nguyên luồng PKCE của dự án nguồn, bật bằng `GOOGLE_CLIENT_ID` + `google_enabled`; tài khoản Google mới đi theo `signup_mode`.

**Bảng mặc định (R11):**

| Khoá | Mặc định | Nguồn thật |
|---|---|---|
| `MAIL_TRANSPORT` | `console` + `WARNING DEFAULTS_APPLIED=[mail_transport]` một lần mỗi process | env |
| `MAIL_FROM` | `no-reply@<domain>` | env |
| `signup_mode` | `default_tenant` | `/sa/settings` |
| `email_verification` | `soft` | `/sa/settings` |
| `AUTH_VERIFY_TOKEN_HOURS` / `AUTH_RESET_TOKEN_MINUTES` | 24 / 60 | env |

### 3.4 Module — một khuôn cho mọi nghiệp vụ (D15)

| Phương án | Nạp động / bật tắt lúc chạy | Số chỗ module phải khai | Scaffold sinh được | Độ phức tạp lõi |
|---|---|---|---|---|
| **Package thường + registry tĩnh** (một dòng ở `DOMAINS` + một dòng ở `modules/registry.ts`) | ✗ | 2 | ✓ | thấp — giống cách dự án nguồn thêm miền |
| Hệ plugin nạp động (cấu hình bật / tắt, migration theo module) | ✓ | 1 | ✓ | cao |

→ Chọn **package thường + registry tĩnh**.

**Khuôn backend** `app/<module>/`: `models.py` (kế thừa `TenantScoped`) · `schemas.py` · `service.py` · `ops.py` (`@operation` với `permission`, `agent=True`, `toolset`, `invalidates`) · `permissions.py` (`register_permissions`) · `agent.py` (`register_toolset`, `register_context`, `register_specialist`) · `errors.py` · `qkeys.py` · `tasks.py` / `consumers.py` khi cần · `prompts/<slug>.md`. Migration `migrations/versions/00NN_<module>.py`; test `tests/<module>/`; câu ý định `tests/agent_eval/<module>_{vi,en}.yaml`.

**Khuôn frontend** `src/modules/<module>/`: `index.ts` (manifest: route, mục menu, "Thêm nhanh", widget Tổng quan, từ điển i18n) · `api.ts` · `keys.ts` · `pages/` · `components/`. `src/modules/registry.ts` liệt kê manifest; layout và router đọc từ đó.

**Dải mã:** lõi giữ 4 chữ số như dự án nguồn (1xxx core · 2xxx auth + tenant · 6xxx agent · 7xxx quan sát + thông báo · 8xxx mail); module dùng 5 chữ số `1NNxx` (Tasks = 10001–10099). Tiền tố `loc` theo tên module, test luật kiểm như dự án nguồn.

**Công cụ tạo module:**
- `make new-module NAME=notes TITLE="Ghi chú"` (`scripts/scaffold/`, mẫu Jinja2) sinh module CRUD chạy được: bảng (`title`, `description`, `status`, `created_by`, `source`, `agent_run_id`), migration, 5 op (list / get / create / update / delete), quyền, toolset + chuyên gia + prompt, câu ý định, test BE (gồm test tách tenant), trang danh sách (thẻ ở điện thoại / bảng ở desktop) + hộp thoại form, i18n vi / en, mục menu.
- Skill Claude Code `.claude/skills/new-module/` (và `new-app/`): hỏi gọn yêu cầu nghiệp vụ → viết doc thiết kế module (ĐỀ XUẤT, bảng R4) → chạy scaffold → sửa field / luật nghiệp vụ → viết prompt chuyên gia + câu ý định → giao test cho subagent Sonnet (R26) → cập nhật tài liệu.
- `make scaffold-check` (trong `make ci`): sinh một module thử vào bản sao tạm rồi chạy test BE + typecheck FE, để scaffold không bị lỗi thời theo lõi.

### 3.5 Agent — một bộ như dự án nguồn, dùng cho mọi tenant

**Giữ nguyên:** Studio, credential mã hoá, xoay key, hạn mức + chặn spam, hook vòng đời, duyệt (gom thẻ), checkpointer, trace + usage, màn chat đơn giản / gỡ lỗi, router + chuyên gia + handoff, LLM giả, `mp dump-chat-session`, `make agent-eval`.

**Một bộ cho mọi tenant:**
- Cấu hình agent (provider, model, key, agent, chuyên gia, hook, persona, hạn mức) là dữ liệu **toàn nền tảng**, chỉ superadmin sửa ở Studio — y như dự án nguồn.
- Lượt chạy dựng principal từ user đang chat (đã có `tenant_id`) → mọi tool đi qua `run_operation` nên **tự** nằm trong tenant đó. LLM không thấy, không truyền tenant.
- Phiên chat, tin nhắn, lượt chạy, yêu cầu duyệt mang `tenant_id` (lọc tự động). Trace + usage có `tenant_id` → `/sa/usage` gộp / lọc theo tenant (chi phí AI từng khách hàng).
- Hạn mức chat thêm tầng tenant (§3.2); tenant tắt trợ lý bằng policy `agent_enabled = false`.

**Phần đang gắn cứng vào ví chuyển thành registry:**

| Chỗ gắn cứng ở dự án nguồn | Thành |
|---|---|
| `TOOLSETS` + `CONFIRM_WRITES` trong `agent/config/toolsets.py` | `register_toolset(name, description, confirm_writes=…)` ở `agent.py` của module; quyền `agent.<toolset>` tự vào catalog |
| `agent/runtime/context.py` đọc ví, nợ, nhóm, phiếu | lõi viết: user, role, tenant, locale, múi giờ, giờ hiện tại; module thêm dòng qua `register_context(fn, budget=…)` |
| 6 chuyên gia + prompt seed trong `seed_data.py` | `register_specialist(slug, name, toolsets, prompt, intents, examples)`; route của orchestrator dựng từ registry; giữ logic nâng bản seed cũ khi chưa sửa ở Studio |
| Tham số `owner` (`user:` / `group:`) trong tool | bỏ — tool tự lọc theo tenant của người đang chat |
| Persona riêng của dự án nguồn (xưng em, emoji) | persona trung tính, trả lời theo `locale` của user; prompt viết tiếng Anh, có ví dụ vi / en |

Template ship 3 agent: orchestrator "Assistant", chuyên gia `general` (tra cứu chung) và `tasks` (module mẫu).

### 3.6 Module mẫu Tasks (D8)

- **Bảng:** `tasks` (`tenant_id`, `title`, `description`, `status` `todo | doing | done | cancelled`, `priority` `low | normal | high | urgent`, `due_at`, `assignee_id`, `position`, `created_by`, `source`, `agent_run_id`, `completed_at`) · `task_comments`.
- **Op:** `tasks.list` (lọc trạng thái / người làm / hạn / tìm chữ, phân trang R14) · `get` · `create` · `update` · `assign` (chỉ user cùng tenant) · `set_status` · `delete` (`destructive` → agent phải duyệt) · `comments.list` / `comments.add` · `tasks.summary` (đếm theo trạng thái, quá hạn — cho widget và agent).
- **Realtime:** mọi op ghi khai `invalidates` + `ctx.invalidate(..., tenant=True)`; được giao việc → thông báo + Web Push.
- **Nền:** cron `tasks.due_reminders` (mỗi 15 phút, lặp từng tenant, idempotent theo `(task, mốc)`) nhắc việc sắp tới hạn / quá hạn.
- **Agent:** toolset `tasks`, chuyên gia `tasks` ("tạo việc gọi khách hàng thứ Sáu giao cho Lan", "tuần này còn gì quá hạn?"); ngữ cảnh: số việc theo trạng thái + 5 việc gần hạn của tôi; ≥ 30 câu ý định mỗi ngôn ngữ.
- **UI:** danh sách (thẻ ở điện thoại / bảng ở desktop) + bộ lọc trên URL, sheet chi tiết + bình luận, "Thêm nhanh" ở cụm nút nổi, widget Tổng quan "Việc của tôi".

### 3.7 i18n (D7)

- FE: chép cơ chế `t()` + từ điển `[vi, en]` + test đủ khoá của dự án nguồn; mỗi module một file từ điển.
- BE: API trả `code` + `message`; FE dịch theo `code` (cách dự án nguồn đang làm với mã agent). Thông báo lưu `kind` + `params`, FE dịch lúc hiển thị (đã có `register_kind`). Mail dịch theo `users.locale`.
- Agent: khối `<context>` có `locale`; persona yêu cầu trả lời đúng ngôn ngữ đó.

### 3.8 Môi trường local (D16)

Dự án nguồn cho dev dùng **chung DB với prod** (D41 của dự án nguồn) — hợp với một người trên một server, không hợp làm mặc định cho template.

| Phương án | Chạy được trên máy mới chỉ với Docker | Đụng dữ liệu thật khi dev | Dùng lại hạ tầng chung trên `<server-ip>` |
|---|---|---|---|
| **`deploy/compose.infra.yml` (Postgres / Redis / RabbitMQ / Mongo) làm mặc định; `.env` trỏ hạ tầng chung khi muốn** | ✓ | ✗ (DB `<slug>_dev`) | ✓ |
| Như dự án nguồn: dev = prod | ✗ | ✓ | ✓ |
| Chỉ compose | ✓ | ✗ | ✗ |

→ Chọn **compose infra làm mặc định, hạ tầng chung là tuỳ chọn**. Giữ nguyên `make dev-up` (namespace `_e2e`); seed chỉ chạy trên DB `_test` / `_e2e` / `_dev` (D43 của dự án nguồn). Seed dev có 2 tenant (`default`, `acme`) để luôn thử được việc tách dữ liệu.

### 3.9 Tài liệu + rule (D6)

- `CLAUDE.md` gốc giữ R1–R28 (giữ ý, đổi ví dụ ví → Tasks / tenant). Rule riêng B1–B13 (backend) và 13 rule frontend giữ nguyên; rule frontend 11 (sổ sách) bỏ. Thêm **B14 — tenant**: model module kế thừa `TenantScoped`, không SQL thô trên bảng tenant, việc nền mở `tenant_session`, Redis key mang `tid`, xem chéo tenant chỉ qua `ctx.cross_tenant()`.
- R26 (phiên chính viết code, test giao **một** subagent Sonnet effort medium) và R22 (Playwright qua subagent) giữ nguyên.
- R27 (push `main` = deploy) và R28 (tự chạy theo plan, báo Discord khi bị chặn) giữ, URL / uuid lấy từ `.secrets/` thay vì ghi cứng.
- Thêm `.claude/platform/playbooks/`: **new-app** (copy → đổi tên → env → Coolify) · **new-module** (thiết kế → scaffold → nghiệp vụ → agent → test → tài liệu) · **upgrade-from-template** (kéo bản sửa lõi từ template sang app đã tách).
- `decisions/` bắt đầu lại từ D1; mục đầu liệt kê các quyết định của dự án nguồn được kế thừa (cờ Mongo, lịch sử chat ở Postgres, superadmin từ env, hook vòng đời, web và agent ngang nhau, realtime-first…).

## 4. Lộ trình (bản gốc — thứ tự thi công thay bằng D17, xem [roadmap](./roadmap.md))

Mỗi SP đi một vòng như dự án nguồn: **plan (package R25) → code → test (subagent Sonnet) → smoke 2 chế độ Mongo → E2E 375 / 1440**.

| SP | Phạm vi | Definition of Done | Lượng việc ước tính |
|---|---|---|---|
| **SP0** | Khung repo + lõi | `git init`; chép `core/`, `system/`, `devtools/`, `realtime/`, deploy, Makefile, docsite, check_md; tên `bw`; `compose.infra.yml`; `CLAUDE.md` + `.claude/` khung; `make ci` + `make dev-up` + `make smoke-local` (phần không đăng nhập) xanh | ~5 k dòng chép |
| **SP1** | Auth + tenant + mail | auth / RBAC / superadmin env / policies (thêm tầng tenant); bảng `tenants`, `TenantScoped` + lọc tự động, `signup_mode`, lời mời email / link, khoá tenant, phòng realtime `tenant:<tid>`; mail `console` + `smtp`, xác thực email, quên mật khẩu, Google | ~3 k chép, ~2 k viết mới |
| **SP2** | Dịch vụ nền + khung UI | thông báo + Web Push, event log / issues, cài đặt hệ thống; khung UI ưu tiên điện thoại, vi / en, PWA; trang auth / hồ sơ / admin / Tổ chức / sa (gồm `/sa/tenants`, `/sa/mail`) | ~9 k chép, ~1 k viết mới |
| **SP3** | Nền agent | chép `agent/` + `credentials/`, registry toolset / ngữ cảnh / chuyên gia, `tenant_id` trên chat / run / trace / usage, persona theo locale, Studio / Trace / Usage (lọc theo tenant) / Chat guard, LLM giả, eval | ~8 k chép + sửa |
| **SP4** | Module Tasks | §3.6 đầy đủ + chuyên gia + ≥ 30 câu ý định mỗi ngôn ngữ (`make agent-eval` ≥ 95 % với model thật) | ~2,5 k viết mới |
| **SP5** | Scaffold + skill + đổi tên | `make new-module`, `make new-app`, `scaffold-check`, `new-app-check`, skill `new-module` / `new-app`, 3 playbook | ~1,5 k viết mới |
| **SP6** | Kiểm + phát hành | HLD + sơ đồ archify, `make docs`, smoke đủ, E2E toàn bộ (375 / 1440, gồm luồng 2 tenant), grep sót tên dự án nguồn = 0, tag `v1.0.0`; (tuỳ chọn) bản demo trên Coolify | — |

Thứ tự: SP0 → SP1 → SP2 → SP3 → SP4 → SP5 → SP6. Tenant nằm ở SP1 vì `users.tenant_id` phải có từ migration đầu; SP5 đặt sau SP4 vì scaffold sinh theo khuôn của Tasks.

## 5. Rủi ro

| Rủi ro | Giảm bằng |
|---|---|
| Bộ lọc tenant tự động bị lách (SQL thô, bảng Core, việc nền quên `tenant_session`) | test luật B14; scaffold sinh test tách tenant cho mọi module; seed dev luôn có 2 tenant; E2E có luồng 2 tenant |
| Tổng quát hoá agent làm hỏng hành vi đã chạy ổn ở dự án nguồn (router, handoff, duyệt song song) | chép bộ test agent của dự án nguồn, đổi sang Tasks, chạy bằng LLM giả trước khi sửa registry |
| Scaffold lỗi thời khi lõi đổi | `make scaffold-check` trong `make ci` |
| Script đổi tên sót chỗ | `make new-app-check` + grep tên cũ = 0 trong app sinh ra |
| App đã tách khó nhận bản sửa lõi từ template | lõi gọn trong `core/ auth/ tenants/ agent/ …`, module ở package riêng; playbook upgrade theo thư mục lõi |
| Khối lượng chép lớn (~17 k dòng BE nền, ~10 k FE, ~20 k test) | chép nguyên trước, chạy test xanh, rồi mới tổng quát hoá từng chỗ |

## 6. Việc chờ chủ dự án

| Việc | Cần cho | Chặn? |
|---|---|---|
| ~~Duyệt tài liệu này~~ — đã duyệt 2026-10-14 | bắt đầu SP0 | — |
| Tạo repo GitHub (private) cho template | push, Coolify | từ SP6 (hoặc sớm hơn nếu muốn deploy demo) |
| Coolify app + domain + tunnel cho bản demo | bản demo | ✗ (tuỳ chọn) |
| Tài khoản SMTP | gửi mail thật | ✗ (`console` đủ để dev / test) |
| Key LLM | `make agent-eval` với model thật | ✗ (test dùng LLM giả) |
| Cho phép tạo DB / vhost / Redis db cho `bizwithagents_*` trên hạ tầng chung | dùng hạ tầng chung thay compose | ✗ |

---

*Cập nhật: 2026-10-14*
