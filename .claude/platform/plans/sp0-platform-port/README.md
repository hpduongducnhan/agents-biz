# SP0 — Chép nền từ dự án nguồn

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [roadmap](../../design/roadmap.md) · [template-v1 §2](../../design/template-v1.md) · [decisions D9, D16–D19](../../design/decisions/d01-current.md)

**Trạng thái:** Xong (2026-10-15) — plan dạng đặc tả (D18). Kết quả: `make ci` xanh, smoke-local 26 / 26 bước cả hai chế độ Mongo.

## Goal

Repo `BizWithAgents` chạy được như một app thật chỉ có phần nền của dự án nguồn (đăng nhập, RBAC, superadmin, thông báo + Web Push, event log / issues, cài đặt hệ thống, credential, agent + Studio + trace / usage, realtime, khung UI ưu tiên điện thoại, PWA, deploy), đổi tên `bw`, không còn nghiệp vụ ví / nhóm / chia tiền / Drive. Chưa có tenant (SP1), agent chưa có tool nghiệp vụ (SP2–SP3).

## Architecture

- Nguồn: repo dự án nguồn tại commit đang có trên đĩa ngày 2026-10-14.
- Chép bằng script trong scratchpad (luật đổi tên bên dưới), rồi sửa tay chỗ dính nghiệp vụ. Script chính thức `make new-app` làm ở SP4.
- Migration bắt đầu lại: chỉ giữ migration của phần nền, đánh số lại liền mạch từ `0001`, bỏ bảng / cột của ví / nhóm.

**Luật đổi tên (D9):**

| Dự án nguồn | Template |
|---|---|
| tên dự án nguồn (3 dạng viết) | `bizwithagents` · `BizWithAgents` · `bizwithagents` |
| tiền tố `mp` đứng riêng (`mp:`, `mp.`, `mp_`, `"mp"`, CLI `mp`, `@mp/…`) | `bw` |
| service `<nguồn>-*` | `bw-*` |
| cổng local 8101 / 8102 / 8103 / 8104 | 8201 / 8202 / 8203 / 8204 |
| cổng container 16801 / 16802 / 16803 | 16811 / 16812 / 16813 |
| domain `<nguồn>.<domain>` | `bizwithagents.<domain>` |

## Global Constraints

- Không sửa gì ở dự án nguồn.
- Giữ nguyên hành vi lõi; chỉ xoá / cắt phần dính nghiệp vụ. Tổng quát hoá (registry, tenant) để SP1–SP2.
- Hạ tầng dev / test: `deploy/compose.infra.yml` (D16) — Postgres `127.0.0.1:15432`, Redis `16379`, RabbitMQ `5673` (+ UI `15673`), Mongo `27018`.
- Rule R1–R28 + B1–B13 áp từ task đầu.

## Tasks

| # | Việc | Kết quả |
|---|---|---|
| T1 | Repo + tài liệu khung | `git init`, `.gitignore`, `.dockerignore`, `CLAUDE.md` (rule R1–R28 viết lại ví dụ), menu `.claude/platform/CLAUDE.md`, decisions, roadmap, plan này |
| T2 | Hạ tầng local | `deploy/compose.infra.yml` + `deploy/postgres/init.sql` + `deploy/rabbitmq/definitions.json` (vhost `bizwithagents`, `bizwithagents_test`, `bizwithagents_e2e`), `.env.example` trỏ compose |
| T3 | Backend nền | chép `app/{core,auth,system,observability,notifications,credentials,devtools,agent}`, `main.py`, `cli.py`, `domains.py`, `models/`; cắt chỗ import `wallet` / `groups` / `split` / `drive`; quyền `group.create` + 8 quyền `agent.<toolset>` ví bỏ; toolset tạm chỉ `lookup`; ngữ cảnh agent chỉ còn user + giờ; seed chỉ "Assistant" + `general` |
| T4 | Migration | chép + đánh số lại migration nền, bỏ bảng / cột ví / nhóm (`users.currency`, `group_limit`…); `bw migrate` chạy sạch trên DB trống |
| T5 | Test backend | chép test nền (core, messaging, operations, rules, auth, observability, notifications, system, credentials, devtools, agent, deploy, gốc), bỏ test ví / nhóm / chia tiền / Drive, sửa cho xanh; độ phủ ≥ 90 % |
| T6 | Realtime | chép `realtime/` + test, đổi tên; bỏ smoke ví / nhóm (`smoke_sp2a`, `smoke_sp5`…); `make rt-cov` ≥ 90 % |
| T7 | Frontend | chép `lib/`, `ui/`, `layout/`, `guards/`, `boot/`, `stores/`, `features/{admin,agent,auth,notifications,observability,push,rbac,system}`, trang `{auth,profile,notifications,admin,sa,settings,assistant,studio,errors,overview}`; bỏ phần ví / nhóm; Tổng quan tạm; logo trung tính; `make fe-*` xanh, độ phủ ≥ 80 % |
| T8 | Deploy + scripts | `compose.yml`, Dockerfile, nginx, `dev_stack.sh`, `stack_env.py`, `smoke_prod.sh`, `deploy.sh`, `notify.sh`, `docs_site.py` + `docsite/`, `check_md.py`, `seed_agent.py`, Makefile |
| T9 | Tài liệu domain | chép + sửa `.claude/{backend,frontend,deploy}/` và `platform/architecture/{auth-rbac,agent-runtime}`; `make docs` |
| T10 | Kiểm + commit | `make ci` xanh; `make dev-up MONGO=on\|off` + `make smoke-local` xanh; grep `<tên nguồn>\|wallet` trong code = 0 (trừ tài liệu nói về nguồn); commit |

## Definition of Done

- `make ci` xanh (docs-check, openapi-check, be-lint, be-cov ≥ 90, rt-typecheck, rt-cov ≥ 90, fe-api-check, fe-lint, fe-typecheck, fe-cov ≥ 80, fe-build).
- `make dev-up MONGO=on` + `make smoke-local MONGO=on`, rồi `off`, đều xanh.
- `grep -rniE '<tên nguồn>|wallet|ví tiền' backend/app realtime/src frontend/src` = 0.

## Self-Review

- Phần nào chép mà chưa chạy test (vd Google OAuth, Web Push thật) ghi vào roadmap mục "chưa kiểm thật".
- Mọi chỗ cắt nghiệp vụ trong agent (toolset, ngữ cảnh, chuyên gia) đánh dấu để SP2 thay bằng registry.

---

*Cập nhật: 2026-10-14*
