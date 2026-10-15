# AGENTS.md — BizWithAgents

Hướng dẫn cho mọi agent lập trình: Codex (OpenAI), Gemini CLI / Antigravity (Google), Claude Code, Cursor…

1. **Luật dự án** ở [CLAUDE.md](CLAUDE.md) (R1–R29) và `.claude/<domain>/CLAUDE.md` — đọc trước khi sửa code; áp dụng cho mọi agent. Chỗ chỉ dành cho Claude (subagent Sonnet chạy Playwright — R22, R26): agent khác tự làm trong phiên.
2. **Skill** (chuẩn Agent Skills) ở `.agents/skills/` — Codex và Gemini CLI tự tìm; bản sao cho Claude Code ở `.claude/skills/`. Sửa bản ở `.agents/skills/` rồi `make skills-sync` (`make ci` kiểm khớp — D26).

| Skill | Khi nào | Câu chat mẫu | Lệnh chính |
|---|---|---|---|
| `new-app` (chỉ có ở template) | vừa clone template, muốn thành app mới | "Tạo app mới tên Task Hub" | `make init-app …` → `make setup` |
| `setup-env` | vừa clone / pull một app về máy | "Dựng môi trường dev cho repo này" | `make setup MODE=local SUPERADMIN=<email> VERIFY=1` |
| `new-module` | thêm tính năng quản lý một loại dữ liệu | "Thêm module ghi chú" | `make new-module NAME=notes TITLE="Ghi chú"` |

3. **Gọi skill:** Codex — `/skills` hoặc `$new-app`; Gemini CLI — `/skills list` (thư mục phải được tin: `/trust`); Claude Code — `/new-app`; hoặc chỉ cần nói câu chat mẫu.
4. **Bản sửa của template về sau:** `make template-sync` (D29) — không `git merge template/main` (tên template lọt vào app). Playbook: `.claude/platform/playbooks/README.md`.
5. **Không đọc / in secret** (`.env`, `.secrets/`, token) — R21. Mọi lệnh chạy qua `make` (tên CLI đổi theo tiền tố app).
