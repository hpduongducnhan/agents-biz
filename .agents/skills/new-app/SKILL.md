---
name: new-app
description: Tạo app mới từ template BizWithAgents ngay sau khi clone / pull về từ git — đổi tên dự án (tên, slug, tiền tố, cổng, Redis db) rồi dựng môi trường dev (phụ thuộc, .env, khoá, hạ tầng Docker, migrate, smoke). Dùng khi người dùng nói "tạo app / dự án mới", "đổi tên dự án", "khởi tạo từ template" (create a new app / rename the project). Không dùng để thêm tính năng (→ new-module) hay chỉ dựng môi trường cho repo đã đổi tên (→ setup-env).
---

# Tạo app mới từ template (sau khi clone)

Làm theo luật ở `CLAUDE.md` — áp dụng cho mọi agent. Không đọc / in `.env`, `.secrets/` (R21). Mọi lệnh đi qua `make`.

## 1. Xác định tình huống

```bash
basename "$PWD"; git status --short | head; git remote -v
```

| Tình huống | Làm |
|---|---|
| Thư mục đã mang tên app (vd `git clone <repo template> taskhub`) | **đổi tên tại chỗ** — bước 3a |
| Thư mục tên `BizWithAgents` / `bizwithagents` (bản template) | **chép sang thư mục mới** — bước 3b |
| `git status` còn thay đổi | nhờ người dùng commit / stash trước |

## 2. Hỏi một lượt (có khuyến nghị — người dùng chỉ cần nói tên)

| Tham số | Khuyến nghị | Luật |
|---|---|---|
| `NAME` | tên người dùng nói, vd `Task Hub` | có chữ / số |
| `SLUG` | `NAME` viết thường, bỏ dấu + dấu cách, vd `taskhub` | `[a-z][a-z0-9]{2,30}`, khác `bizwithagents` |
| `PREFIX` | chữ cái đầu mỗi từ, vd `th` | 2–4 chữ thường, khác `bw` |
| `PORTS` | `83` (máy đã có app dùng 83 thì 84, 85…) | 2 chữ số, khác `82` → cổng 8301–8304 |
| `REDIS_DBS` | `4,5,6` (hỏi chủ dự án db còn trống) | 3 số 0–15 (Redis có 16 db), khác `10,11,12` và db app khác đang dùng trên Redis chung (`.claude/deploy/CLAUDE.md`) |
| Hạ tầng | `local` — Docker trên máy | `shared` = hạ tầng chung trên server (D19), chủ dự án tạo DB / vhost |
| Email superadmin | email của người dùng | thêm vào `SUPERADMIN_EMAILS` |

## 3a. Đổi tên tại chỗ

```bash
make init-app NAME="Task Hub" SLUG=taskhub PREFIX=th PORTS=83 REDIS_DBS=4,5,6
```

Lệnh kiểm công cụ, cài `backend/.venv`, đổi tên mọi nơi (bỏ qua `.git`, `node_modules`, `.venv`, `.env`), bỏ công cụ chỉ của template, format + sinh lại tài liệu, đổi remote `origin` → `template` (còn kéo được bản sửa của template) rồi commit "chore: tạo … từ template". Bị chặn thì đọc dòng `init-app:` và làm theo.

## 3b. Chép sang thư mục mới

```bash
make new-app NAME="Task Hub" SLUG=taskhub PREFIX=th PORTS=83 REDIS_DBS=4,5,6 DEST=../taskhub
```

Các bước sau chạy cho thư mục mới: `make -C ../taskhub setup …`.

## 4. Dựng môi trường

```bash
make setup MODE=local SUPERADMIN=<email> VERIFY=1
```

Chi tiết + cách sửa lỗi: skill `setup-env`. `MODE=shared` dừng ở bước `.env` tới khi chủ dự án điền mật khẩu.

## 5. Báo người dùng

- Kết quả từng bước (✓ / ✗) và smoke.
- Việc của chủ dự án: repo GitHub mới (`git remote add origin <url>` → `git push -u origin main`), app Coolify + domain + `PUBLIC_URL` (`.claude/deploy/CLAUDE.md`); MODE=shared: DB `<slug>` / `_test` / `_e2e`, vhost, Mongo DB, Redis db.
- Sửa mục Project Context trong `CLAUDE.md` + `README.md` cho đúng sản phẩm; thêm tính năng bằng skill `new-module`.
- Bản sửa của template về sau: `make template-sync` (không `git merge template/main`).
- Bước 3b: mở thư mục mới bằng agent để làm tiếp.
