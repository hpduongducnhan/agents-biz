---
name: setup-env
description: Dựng môi trường dev cho repo app làm từ template BizWithAgents vừa clone / pull về — kiểm công cụ, cài phụ thuộc backend / realtime / frontend, tạo .env + khoá, hạ tầng (Docker local hoặc hạ tầng chung), migrate, chạy thử + smoke. Dùng khi người dùng nói "setup / dựng / cài môi trường", "chạy app trên máy", "pull về rồi chạy" (set up the dev environment). Không dùng để đổi tên dự án (→ new-app).
---

# Dựng môi trường dev

Không đọc / in `.env`, `.secrets/` (R21) — script tự ghi và chỉ báo tên biến. Luật chung ở `CLAUDE.md`.

## 1. Hỏi một lượt (có khuyến nghị)

| Câu | Khuyến nghị |
|---|---|
| Hạ tầng | `local` — Docker trên máy, tự động hết. `shared` khi máy nối hạ tầng chung có sẵn (D19) |
| Email superadmin | email của người dùng — đăng ký bằng email này là thành superadmin |
| Chạy thử + smoke | có (`VERIFY=1`, thêm vài phút) |

## 2. Chạy

```bash
make setup MODE=local SUPERADMIN=<email> VERIFY=1
```

Các bước (chạy lại vô hại): công cụ (git, Python 3.13, Poetry, Node ≥ 22.18, Docker khi local) → phụ thuộc → `.env` + `CREDENTIAL_KEYS` → khoá JWT → hạ tầng → kiểm cấu hình → migrate → (VERIFY) stack thử có user test + smoke. Log đầy đủ: `debug/setup.log`.

## 3. Sửa lỗi hay gặp

| Dòng ✗ | Làm |
|---|---|
| thiếu python3.13 / poetry / node / docker | cài theo gợi ý trong dòng báo rồi chạy lại |
| `.env` còn chỗ phải điền | MODE=shared: chủ dự án điền mật khẩu (agent không ghi hộ); hoặc xoá `.env` rồi `make setup` (local) |
| cổng đang bận | hạ tầng local của app khác đang chạy → `make infra-down` bên đó, hoặc MODE=shared |
| migrate lỗi kết nối | `docker compose -f deploy/compose.infra.yml ps`; đọc `debug/setup.log` |
| smoke đỏ | `make dev-status`; log ở `.dev-stack/*.log` |

## 4. Báo người dùng

- Kết quả từng bước + cách chạy khi phát triển (in ở cuối lệnh): `make api` · `consume` · `work` · `schedule` · `realtime` · `fe-dev`, hoặc cả stack chạy nền `make dev-up`.
- Đăng nhập: đăng ký bằng email superadmin (thư xác thực ở `/sa/mail`); stack `dev-up` có sẵn `superadmin@test.local` (mật khẩu `SEED_PASSWORD` trong `.env`).
- Key LLM thật: `/studio` → "Gắn model + key cho mọi agent".
