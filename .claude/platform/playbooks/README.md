# Playbook — tạo app mới, dựng môi trường, thêm module, đồng bộ template

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [platform/CLAUDE.md](../CLAUDE.md) · [tasks-module](../architecture/tasks-module.md) · [plan SP4](../plans/sp4-scaffold/README.md) · [plan SP6](../plans/sp6-agent-skills/README.md) · [deploy](../../deploy/CLAUDE.md)

**Trạng thái:** ĐÃ CHỐT (SP4, SP6, D29). Làm bằng chat với Claude Code, Codex hoặc Gemini CLI qua skill (D26) — hoặc gõ lệnh `make` ở bảng dưới.

## 0. Bằng chat (Claude Code / Codex / Gemini)

| Skill (`.agents/skills/` = bản gốc · `.claude/skills/` = bản sao) | Câu chat mẫu | Gọi thẳng |
|---|---|---|
| `new-app` (chỉ ở template) | "Tạo app mới tên Task Hub" | Claude `/new-app` · Codex `$new-app` · Gemini `/skills list` |
| `setup-env` | "Dựng môi trường dev cho repo này" | `/setup-env` · `$setup-env` |
| `new-module` | "Thêm module ghi chú" | `/new-module` · `$new-module` |

- Codex đọc `AGENTS.md` + `.agents/skills/`; Gemini CLI đọc `AGENTS.md` (qua `.gemini/settings.json`) + `.agents/skills/` sau khi tin thư mục (`/trust`); Claude Code đọc `CLAUDE.md` + `.claude/skills/`.
- Sửa skill ở `.agents/skills/` rồi `make skills-sync`; `make ci` chạy `skills-check`.

## 1. App mới — clone rồi đổi tên tại chỗ (D27)

| Bước | Lệnh / việc | Ai |
|---|---|---|
| 1 | `git clone <repo template> taskhub && cd taskhub` | người dùng |
| 2 | `make init-app NAME="Task Hub" SLUG=taskhub PREFIX=th PORTS=83 REDIS_DBS=4,5,6` — đổi tên mọi nơi, bỏ công cụ chỉ của template, `origin` → `template`, commit | agent |
| 3 | `make setup MODE=local SUPERADMIN=<email> VERIFY=1` (§2) | agent |
| 4 | Repo GitHub mới → `git remote add origin <url>` → `git push -u origin main`; app Coolify + domain + `PUBLIC_URL` → `make smoke-prod` (R27) | chủ dự án + agent |
| 5 | Sửa Project Context trong `CLAUDE.md`; thêm module (§3) | agent |

- Đang đứng ở bản template (thư mục `BizWithAgents`): `make new-app … DEST=../taskhub` chép sang thư mục mới + `git init` rồi `make -C ../taskhub setup` (lệnh tự cài `backend/.venv` nếu chưa có).
- `init-app` từ chối khi thư mục còn tên template, cây git chưa sạch hoặc repo đã đổi tên; không cần Docker (chỉ `setup` MODE=local cần).
- Cả hai ghi `.template.json` (tham số đổi tên + commit template) — `make template-sync` đọc (§1.1).
- Đổi tên cũng dời cổng hạ tầng local + LLM giả: +100 × (`PORTS` − 82) — `PORTS=83` → Postgres 15532 · Redis 16479 · RabbitMQ 5773 / 15773 · Mongo 27118 · LLM giả 8899, nên hạ tầng local và stack thử của nhiều app chạy cùng lúc được.
- `make new-app-check` (trước release template) đi đúng đường này trên bản clone giả ở thư mục tạm: không còn tên template, remote `template`, cây sạch, `make template-sync` với một bản sửa thử của template, lint + test không hạ tầng xanh.
- Sơ đồ [HLD](../../HLD/HLD.md) đổi tên bằng thay chữ cả spec lẫn HTML rồi khoá lại (`docs_site.py --relock-diagrams`) — không cần archify; sửa spec về sau thì `make diagrams` (cần archify).

### 1.1 Kéo bản sửa của template — `make template-sync` (D29)

Không `git merge template/main`: file mới của template sẽ vào app với tên template mà git không báo, và mọi dòng có tên đều xung đột.

| Bước | Lệnh / việc |
|---|---|
| 1 | Cây git sạch; có remote `template` (`init-app` đặt sẵn; app tạo bằng `new-app DEST`: `git remote add template <url>`) |
| 2 | `make template-sync [REF=template/main]` — fetch → lấy `new_app.py` + `template_sync.py` mới nhất của template → đổi tên bản template đã đồng bộ và bản mới bằng luật của `init-app` → `cherry-pick` phần chênh → cập nhật `template_commit` trong `.template.json` |
| 3 | Xung đột (app và template cùng sửa một chỗ): sửa giữ tên app → `git add` → `git cherry-pick --continue`. File sinh (`.claude/**/*.html`, `search-index.js`, `openapi.json`, `schema.d.ts`) lấy bản nào cũng được rồi sinh lại |
| 4 | `make docs openapi fe-gen-api` → `make ci` → commit nếu có file sinh lại → deploy (R27) |

- Lệnh báo ✗ "còn tên template" khi luật đổi tên chưa phủ chỗ mới → sửa tay file được liệt kê.
- Bỏ giữa chừng: `git cherry-pick --abort && git checkout HEAD -- .template.json`.

## 2. Dựng môi trường — `make setup` (D28)

| Bước (chạy lại vô hại) | Chi tiết |
|---|---|
| Công cụ | git · Python 3.13 · Poetry · Node ≥ 22.18 (khuyến nghị 24) · npm · Docker + compose (MODE=local) |
| Phụ thuộc | `make be-install rt-install fe-install` |
| `.env` | chưa có → chép `.env.example`; MODE=local dùng các dòng `# compose:`; sinh `CREDENTIAL_KEYS`; `SUPERADMIN=` thêm vào `SUPERADMIN_EMAILS`. Có sẵn → giữ nguyên |
| Khoá JWT | `make keys` → `.secrets/jwt_*.pem` |
| Hạ tầng | local: kiểm cổng → `make infra-up` (chờ healthy); shared: `.env` còn `<mật khẩu>` → dừng, chủ dự án điền rồi chạy lại |
| Kiểm + migrate | `make check-config` → `make migrate` |
| VERIFY=1 | `make dev-up MONGO=on` (stack thử có user test) → `make smoke-local MONGO=on` |

Không in giá trị secret; log đủ ở `debug/setup.log`. DB dev không seed user test (chỉ DB `_test` / `_e2e`) — đăng ký bằng email trong `SUPERADMIN_EMAILS` là thành superadmin; stack `dev-up` có sẵn `superadmin@test.local`.

## 3. Module mới

| Bước | Lệnh / việc |
|---|---|
| 1 | Hỏi một lượt: tên, field, quyền, câu chat mẫu (R4) → doc `<module>-module.md` ĐỀ XUẤT |
| 2 | `make new-module NAME=notes TITLE="Ghi chú" TITLE_EN="Notes"` — sinh khung + chèn 6 dòng đăng ký + dump OpenAPI |
| 3 | Sửa field / luật / prompt / ≥ 30 câu ý định mỗi ngôn ngữ; test BE + FE |
| 4 | `make ci` (có `scaffold-check`) → smoke 2 chế độ Mongo → E2E Playwright (R22) → tài liệu → commit |

Module sinh ra qua `make ci` ngay (kiểm bằng `scaffold-check` trong CI). Test lõi so khớp "lõi cố định + module tuỳ ý" nên không phải sửa test lõi.

## 4. Lỗi hay gặp

| Triệu chứng | Nguyên nhân | Sửa |
|---|---|---|
| `init-app:` thư mục là bản template | đang ở thư mục `BizWithAgents` | clone sang thư mục tên app, hoặc `make new-app DEST=…` |
| `init-app:` cây git chưa sạch | còn thay đổi chưa commit | commit / stash rồi chạy lại |
| `setup`: cổng đang bận | hạ tầng local khác dùng cổng (app chưa đổi tên, hoặc dịch vụ khác) | `make infra-down` ở app kia, hoặc `MODE=shared` |
| `setup`: `.env` còn chỗ phải điền | MODE=shared, chưa có mật khẩu hạ tầng chung | chủ dự án điền; hoặc xoá `.env` → `make setup` (local) |
| Gemini không thấy skill | thư mục chưa được tin | `/trust` rồi khởi động lại, `/skills list` |
| `template-sync:` thiếu `.template.json` | chạy ở bản template, hoặc app tạo trước D29 | chỉ chạy trong app; app cũ: ghi tay file (tham số đổi tên + sha commit template đã dùng) |
| `template-sync:` đang dở một lần đồng bộ | còn xung đột chưa sửa | sửa → `git cherry-pick --continue`, hoặc `--abort` (§1.1) |
| `make ci` báo `skills-check` | sửa `.claude/skills/` thay vì bản gốc | sửa `.agents/skills/` → `make skills-sync` |
| `make new-module` báo "đã có" | thư mục `backend/app/<module>` tồn tại | chọn tên khác hoặc xoá bản dở |
| Test lõi đỏ sau khi thêm quyền / toolset | test so khớp cứng danh sách | so "lõi ⊆ thực tế", như `tests/test_domains.py` |
| Trợ lý không gọi tool mới | toolset chưa gắn cho chuyên gia / user thiếu `agent.<toolset>` | `register_specialist(..., toolsets=…)`, role nhận quyền qua `register_toolset(roles=…)` |
| Hai app đụng dữ liệu Redis | trùng `REDIS_DBS` trên Redis chung | mỗi app một bộ db (D19) — db đang dùng ở [deploy](../../deploy/CLAUDE.md) |
| `docs-check` báo "sơ đồ cũ" | sửa spec `diagrams/*.json` mà chưa sinh lại | `make diagrams` (cần archify) rồi `make docs` |

---

*Cập nhật: 2026-10-15*
