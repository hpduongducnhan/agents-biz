# BizWithAgents

Template fullstack có sẵn trợ lý AI: đăng nhập + phân quyền, tách dữ liệu theo tổ chức (tenant), realtime, thông báo + Web Push, trợ lý AI (Studio, trace, duyệt, hạn mức), giao diện ưu tiên điện thoại + PWA, deploy Coolify. Mỗi app mới = clone → đổi tên → thêm module nghiệp vụ (module mẫu: Tasks).

**Stack:** Python 3.13 (FastAPI, FastStream + taskiq trên RabbitMQ, SQLAlchemy + Alembic, LangChain / LangGraph) · Node + Socket.IO · React 19 + Vite + Tailwind 4 · Postgres · Redis · RabbitMQ · Mongo (tuỳ chọn).

## Bắt đầu nhanh

Cần: git, Python 3.13, Poetry 2, Node ≥ 22.18 (khuyến nghị 24); Docker nếu chạy hạ tầng trên máy.

**Bằng chat** — Claude Code, Codex hoặc Gemini CLI (skill ở `.agents/skills/`, bản sao `.claude/skills/`):

```bash
git clone <repo template> taskhub && cd taskhub
```

Mở agent trong thư mục rồi nói *"Tạo app mới tên Task Hub"* (skill `new-app`: đổi tên + dựng môi trường), sau đó *"Thêm module ghi chú"* (skill `new-module`). Vừa clone một app có sẵn: *"Dựng môi trường dev"* (skill `setup-env`).

**Bằng lệnh:**

```bash
git clone <repo template> taskhub && cd taskhub
make init-app NAME="Task Hub" SLUG=taskhub PREFIX=th PORTS=83 REDIS_DBS=4,5,6  # đổi tên tại chỗ + commit
make setup MODE=local SUPERADMIN=you@example.com VERIFY=1                       # phụ thuộc, .env, khoá, Docker, migrate, smoke
make new-module NAME=notes TITLE="Ghi chú" TITLE_EN="Notes"                     # thêm module nghiệp vụ
make template-sync                                                              # về sau: kéo bản sửa của template
```

Chạy khi phát triển: `make api` · `make consume` · `make work` · `make schedule` · `make realtime` · `make fe-dev` (mỗi lệnh một terminal), hoặc cả stack chạy nền `make dev-up`. Kiểm trước khi commit: `make ci`.

## Tài liệu

| Chủ đề | Ở đâu |
|---|---|
| Luật dự án (mọi agent) | [CLAUDE.md](CLAUDE.md) · [AGENTS.md](AGENTS.md) |
| Tạo app · dựng môi trường · thêm module · đồng bộ template | [playbooks](.claude/platform/playbooks/README.md) |
| Kiến trúc | [HLD + sơ đồ](.claude/HLD/HLD.md) · [thiết kế tổng](.claude/platform/design/template-v1.md) · [quyết định](.claude/platform/design/decisions/README.md) |
| Deploy | [Coolify, hạ tầng chung](.claude/deploy/CLAUDE.md) |

Trang tài liệu HTML: `make docs` rồi mở `.claude/index.html`.
