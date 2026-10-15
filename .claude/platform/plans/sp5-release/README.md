# SP5 — Kiểm + phát hành v1.0.0

> **Backlinks:** [CLAUDE.md](../../../../CLAUDE.md) | [roadmap](../../design/roadmap.md) · [template-v1](../../design/template-v1.md) · [decisions](../../design/decisions/README.md) · [playbooks](../../playbooks/README.md)

**Trạng thái:** ĐÃ CHỐT (2026-10-15) — plan dạng đặc tả (D18). **Xong** 2026-10-15 — kết quả ở [roadmap](../../design/roadmap.md).

## Goal

Template sạch dấu vết dự án nguồn trong code, có tài liệu tổng quan (HLD + sơ đồ) cho người mới, mọi kiểm tra xanh trên một commit, gắn tag `v1.0.0`; việc còn lại của chủ dự án (repo GitHub, hạ tầng chung, Coolify) liệt kê rõ.

## Architecture

| Việc | Cách |
|---|---|
| Tên còn sót | `MpLogger` → `AppLogger`, `MpTask` → `AppTask`, `MP_DOCS_SEARCH` → `DOCS_SEARCH`; tên dự án nguồn trong code chỉ còn ở chỗ nói về nguồn chép (không có) |
| Tham chiếu tài liệu dự án nguồn trong comment (R3) | bỏ `SP<n>` / `v1-design §…` / `sp*-index §…` / `D<n>` của dự án nguồn (D > 25, hoặc dòng chép từ SP0 nhắc D cũ); giữ ý, thay bằng mô tả ngắn hoặc trỏ tài liệu template (`agent-runtime`, `tenancy`…) khi cần; giữ `D1–D25` của template |
| HLD | `.claude/HLD/HLD.md` + sơ đồ archify (`diagrams/*.json` → HTML tương tác — `make diagrams`, R23): triển khai Coolify, dữ liệu (Postgres + Redis, RabbitMQ, Mongo + dịch vụ ngoài), lớp logic + `@operation`, use case (đăng nhập + socket, mời vào tổ chức, một lượt chat, tạo việc + realtime theo tổ chức, deploy), vòng đời lượt chạy agent |
| Kiểm | `make ci` (có `scaffold-check`), `make new-app-check`, `make smoke-local` hai chế độ Mongo, E2E SP1–SP3 chạy lại (`scripts/e2e/sp{1,2,3}_*.py`), grep tên dự án nguồn trong code = 0 |
| Phát hành | commit + tag `v1.0.0` (local — repo GitHub là việc chủ dự án); `notify` chủ dự án danh sách việc còn lại |

## Tasks

| # | Việc | Kết quả |
|---|---|---|
| T1 | Đổi tên `Mp*` + dọn tham chiếu dự án nguồn trong comment code | grep = 0; test luật mới: code không nhắc `v1-design` / `sp\d+-index` (tên dự án nguồn: `make secrets-scan`) |
| T2 | HLD + 8–10 sơ đồ | `.claude/HLD/` link từ CLAUDE.md |
| T3 | Kiểm toàn bộ | các lệnh ở trên xanh trên cùng commit |
| T4 | Tag + thông báo chủ dự án | `v1.0.0`, `scripts/notify.sh` |

## Definition of Done

- `git grep -i <tên nguồn> -- backend/app frontend/src realtime/src scripts` = 0; không còn `v1-design` / `sp1-index` trong code.
- Mọi kiểm tra ở T3 xanh; roadmap ghi kết quả; tag `v1.0.0`.

## Self-Review

- Dọn comment là refactor thuần — không đổi code chạy; test đầy đủ chạy lại sau khi dọn.
- Thực tế làm: ngoài comment còn sót chữ nghiệp vụ dự án nguồn trong prompt gửi LLM (`CONTEXT_NOTE`: "ví, nợ, nhóm"; mô tả bước router: "số tiền / ví") và docstring schema thông báo → viết lại chung; test luật `test_no_source_refs.py` chặn `v1-design` / `sp*-index` trong code; tên riêng (dự án nguồn, domain, IP) chặn bằng `make secrets-scan` với danh sách cục bộ `.secrets/private-terms.txt`.
- archify 3: không xuất SVG (chỉ HTML tương tác); sơ đồ kiến trúc rộng ≤ ~1240 để chữ cạnh ≥ 6px ở khung 930; sequence cần `meta.viewBox` đủ rộng + nhãn ngắn ở cột phải.
- `make new-app` đổi chữ trong spec + HTML sơ đồ → khoá lệch → thêm `docs_site.py --relock-diagrams` (khoá lại theo file đang có, không cần archify); `new-app-check` xanh lại.
- E2E SP2 S2 (1440) đỏ đều đặn ngay sau khi dựng lại stack: lượt chat đầu của worker mới chờ `init_chat_model` import gói provider (~0,45 s openai, ~1 s anthropic) → chữ stream tới trễ ~0,9 s. Sửa ở sản phẩm: `bw work` có lane `agent-run` nạp sẵn provider trước khi nhận task (`agt1001`); E2E chờ socket nối trước khi gửi. Stack nguội: SP2 12 / 12.

---

*Cập nhật: 2026-10-15*
