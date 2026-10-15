# SP6 — Skill cho Claude Code / Codex / Gemini: tạo app sau khi clone + dựng môi trường

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [roadmap](../../design/roadmap.md) · [decisions](../../design/decisions/README.md) · [playbooks](../../playbooks/README.md) · [sp4-scaffold](../sp4-scaffold/README.md)

**Trạng thái:** ĐÃ CHỐT (2026-10-15) — plan dạng đặc tả (D18), yêu cầu của chủ dự án; quyết định D26–D28; bổ sung sau review: D29. **Xong** 2026-10-15 — kết quả ở [roadmap](../../design/roadmap.md).

## Goal

Clone template từ git về, mở bằng Claude Code, Codex hoặc Gemini CLI rồi nói bằng chat "tạo app Task Hub" là xong: đổi tên tại chỗ, cài phụ thuộc, `.env`, khoá, hạ tầng, migrate, user test, smoke. Người clone một app có sẵn chỉ cần "dựng môi trường".

## Architecture

| Phần | Cách |
|---|---|
| Skill (D26) | Bản gốc `.agents/skills/<tên>/SKILL.md` (chuẩn Agent Skills: Codex đọc `.agents/skills`, Gemini CLI đọc `.agents/skills` = bí danh `.gemini/skills`); bản sao y hệt ở `.claude/skills/` cho Claude Code — `scripts/skills_sync.py` chép, `make skills-check` (trong `make ci`) bắt lệch |
| Bộ skill | `new-app` (chỉ ở template) · `setup-env` (mọi app) · `new-module` (mọi app — sửa lời cho agent bất kỳ) |
| Ngữ cảnh agent | `AGENTS.md` ở gốc (Codex tự đọc): trỏ CLAUDE.md là luật chung + danh sách skill; `.gemini/settings.json` → `context.fileName = ["AGENTS.md", "GEMINI.md"]` |
| Đổi tên tại chỗ (D27) | `make init-app NAME=… SLUG=… PREFIX=… PORTS=… REDIS_DBS=…` trong bản clone: kiểm cây git sạch + thư mục không mang tên template → `be-install` → đổi tên (bỏ `.git`, `node_modules`, `.venv`, `.env`…) → bỏ công cụ chỉ của template → `ruff format` + sinh lại tài liệu → remote `origin` đổi thành `template` → commit. `make new-app DEST=…` (chép sang thư mục mới) giữ nguyên |
| Dựng môi trường (D28) | `make setup [MODE=local\|shared] [SUPERADMIN=email] [VERIFY=1]` — `scripts/setup_env.py` (chỉ thư viện chuẩn), chạy lại vô hại: kiểm công cụ → cài phụ thuộc → `.env` → `CREDENTIAL_KEYS` bền → khoá JWT → hạ tầng (local: `make infra-up` + chờ healthy; shared: kiểm còn `<mật khẩu>`) → `check-config` → migrate → user test → (VERIFY) `dev-up` + `smoke-local` |
| Kiểm | `new-app-check` đi đúng đường người dùng: chép cây làm như bản clone (git init + remote `origin`) → `init-app` tại chỗ → không còn tên template → lint + test không hạ tầng; test đơn vị cho `setup_env.py`, `skills_sync.py`, `new_app.py --in-place` |

## Global Constraints

- Không in / đọc giá trị secret (R21): `setup_env.py` ghi `.env` (khoá Fernet sinh bằng `os.urandom`) nhưng chỉ in tên biến; agent không mở `.env`.
- Skill viết trung lập agent: phần riêng Claude (subagent Sonnet cho Playwright — R22) ghi rõ "Claude Code"; agent khác tự chạy.
- Lệnh trong skill đi qua `make` (tên CLI đổi theo tiền tố app).

## Tasks

| # | Việc | Kết quả |
|---|---|---|
| T1 | `.agents/skills/{new-app,setup-env,new-module}` + `skills_sync.py` + `make skills-sync` / `skills-check` (trong `ci`) | `.claude/skills/` khớp |
| T2 | `AGENTS.md`, `.gemini/settings.json` | Codex / Gemini nạp luật + thấy skill |
| T3 | `new_app.py --in-place` + `make init-app` + `new-app-check` theo đường clone | test đơn vị + check xanh |
| T4 | `setup_env.py` + `make setup` / `check-config` | test đơn vị; chạy thật MODE=local trên bản clone tạm |
| T5 | Tài liệu: playbooks, decisions D26–D28, roadmap, CLAUDE.md | `make docs` |

### Bổ sung sau review (2026-10-15, D29)

| # | Việc | Kết quả |
|---|---|---|
| T6 | `make new-app` tự kiểm công cụ + `be-install` (bản clone mới chưa có `backend/.venv` → `not found`); `init-app` / `new-app` kiểm công cụ ở chế độ `shared` (không đòi Docker) | chạy thật `make new-app` trên bản `git clone` mới |
| T7 | `make template-sync` (`scripts/scaffold/template_sync.py`, chỉ của template — app lấy bản mới nhất từ remote `template`); `init-app` / `new-app` ghi `.template.json`; playbook §1.1 | test đơn vị (repo git nhỏ: đổi tên dòng sửa + file mới, giữ phần app sửa, xung đột, chỉ đổi công cụ template, chặn cây bẩn); `new-app-check`: clone → `init-app` → template có bản sửa → `make template-sync` |
| T8 | `README.md` gốc · HLD (đường tạo app mới) · `fake-llm` vào `.PHONY` | `make docs` |

## Definition of Done

- `make ci` (có `skills-check`) xanh; `make new-app-check` xanh qua đường `init-app` tại chỗ.
- Chạy thật trên bản clone tạm: `make init-app` → `make setup MODE=local VERIFY=1` → smoke xanh.
- (D29) `new-app-check` xanh có bước `make template-sync`; `make new-app` chạy được trên bản `git clone` mới.

## Self-Review

- Gemini CLI cần tin thư mục (`/trust`) mới nạp skill workspace; ghi ở playbook.
- Hai app cùng chạy hạ tầng local từng trùng cổng → đổi tên app dời cổng hạ tầng local + LLM giả +100 × (`PORTS` − 82) (test: 90 giá trị `PORTS` không trùng nhau); `setup` vẫn kiểm cổng bận (dịch vụ khác) trước `infra-up`.
- Lỗi có sẵn từ SP4 lộ ra khi viết test: ví dụ `REDIS_DBS=20,21,22` trong skill / Makefile / playbook không hợp lệ (Redis chỉ có db 0–15) → gợi ý `4,5,6` (db 0–3, 8, 13, 14 đang có app khác dùng trên Redis chung).
- `seed-test-users` chỉ chạy trên DB `_test` / `_e2e` (an toàn có chủ đích) → `setup` không seed DB dev; superadmin đầu tiên = đăng ký bằng email `SUPERADMIN=`; `VERIFY=1` dựng stack thử có user test.
- Review sau phát hành tìm ra: `make new-app` hỏng trên bản clone mới (thiếu `.venv`), `init-app` đòi Docker dù đổi tên không cần, thiếu đường kéo bản sửa của template (playbook upgrade đã hứa ở template-v1 §3.9 / §5; `git merge template/main` để lọt tên template qua file mới) → T6–T8.
- Chạy thật trên bản clone giả `taskhub`: `make init-app` (290 file đổi, 5 công cụ template xoá, remote `template`, cây sạch) → `make setup MODE=local SUPERADMIN=… VERIFY=1` xanh hết (hạ tầng riêng cổng 15532 / 16479 / 5773 / 27118, smoke qua 8301); chạy lại `setup` vô hại; dọn sạch container / volume thử.

---

*Cập nhật: 2026-10-15*
