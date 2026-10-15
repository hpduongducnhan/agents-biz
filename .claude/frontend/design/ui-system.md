# Frontend — UI system (ưu tiên điện thoại)

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [frontend/CLAUDE.md](../CLAUDE.md) · [decisions](../../platform/design/decisions/README.md) · [platform/auth-rbac §9](../../platform/architecture/auth-rbac.md)

**Trạng thái:** ĐÃ CHỐT (chép từ dự án nguồn ở SP0).
- Token ngữ nghĩa, dark / light ba lớp, i18n, a11y, checklist; **ưu tiên điện thoại**; bảng / thẻ theo R16; JSON theo R17.
- Token sống ở `frontend/src/index.css`. App làm từ template đổi bảng màu thương hiệu ở đây và trong `index.css` (giữ test tương phản).

---

## 0. Ngôn ngữ thị giác

- App dùng hằng ngày bằng một tay: chữ vừa, vùng bấm rộng, ít chrome, số liệu nổi bật (`tabular-nums`).
- Palette thương hiệu: brand `#4F40DD` (Indigo), brand-soft `#A99FFF` (Lavender), accent `#F8B44A` (Honey), surface `#FFF7ED` (Cream), ink `#1C1745` (Ink). Mọi màu khác là token ngữ nghĩa dẫn xuất (§2), đạt WCAG AA cho mọi cặp chữ / nền.
- Font Nunito (đủ dấu tiếng Việt, bo tròn). Logo: `frontend/public/brand/` (mark + lockup sáng / tối, PNG 16–512 cho PWA).

## 1. Nguyên tắc bất biến

1. Thiết kế ở 375px trước; không cuộn ngang ở 375 / 768 / 1024 / 1440.
2. Chỉ semantic token trong component.
3. Nhịp 4 / 8px.
4. Motion 120–320ms; tôn trọng `prefers-reduced-motion`.
5. Icon `lucide-react`, không emoji.
6. Không màu đơn kênh: trạng thái / thu chi luôn kèm icon hoặc nhãn.

## 2. Token

Giá trị sống ở `frontend/src/index.css`; `test/lib/theme.test.ts` kiểm mọi cặp chữ / nền ≥ 4.5 ở cả hai theme.

| Token (`--color-*`) | Vai trò | Sáng | Tối |
|---|---|---|---|
| `background` / `foreground` | nền trang / chữ chính | `#FFF7ED` / `#1C1745` | `#0E0D16` / `#ECEBF5` |
| `card` · `popover` | mặt nổi: thẻ, bảng · menu, dialog | `#FFFFFF` · `#FFFFFF` | `#181725` · `#1E1D2D` |
| `muted` / `muted-foreground` | nền phụ (chip, ô icon) / chữ phụ | `#F6EEE3` / `#5B5680` | `#201F2F` / `#A3A0BC` |
| `accent` · `secondary` | hover, mục đang focus · nút phụ | `#F1EDFF` · `#EEEBFF` | `#262539` · `#252436` |
| `border` · `input` | viền · viền ô nhập, rãnh switch | `#E9DFD2` · `#DCD0C2` | `#2A293D` · `#3A3954` |
| `primary` / `primary-foreground` | **nền** nút chính, ô chọn, bong bóng chat của user | `#4F40DD` / `#FFFFFF` | `#6354F0` / `#FFFFFF` |
| `brand` | **chữ / icon** nhấn: link, mục đang chọn, tên chuyên gia | `#4F40DD` | `#ADA3FF` |
| `brand-muted` | nền nhấn nhẹ: mục sidebar đang chọn, banner, avatar | `#ECE9FF` | `#24214B` |
| `ring` | viền focus | `#4F40DD` | `#ADA3FF` |
| `sidebar` · `sidebar-border` · `sidebar-accent` | sidebar desktop | `#FFFBF5` · `#EFE5D8` · `#F1EDFF` | `#12111C` · `#222131` · `#1F1E2D` |
| `highlight` | Honey: mục nổi bật, đang chờ | `#F8B44A` | `#F5B54A` |
| `positive` · `negative` (= `destructive`) · `warning` | thu · chi, lỗi · cảnh báo | `#1E7A4C` · `#C8322B` · `#9A5B00` | `#4ACB8B` · `#F47A7A` · `#F5B54A` |
| `chart-1…8` | màu chuỗi biểu đồ | indigo, xanh lá, đỏ, vàng, cyan, tím, hồng, slate | cùng thứ tự, sáng hơn một nấc |

Quy tắc dùng:
- **`primary` là màu nền, `brand` là màu chữ.** Nền đặc có chữ trắng → `bg-primary text-primary-foreground`; chữ / icon nhấn trên nền trang hay thẻ → `text-brand`. Ở theme sáng hai token trùng nhau; ở theme tối không có màu nào vừa đủ sáng làm chữ trên nền tối vừa đủ đậm cho chữ trắng đè lên (tích hai tỉ lệ = 1.05 / (L_nền + 0.05) ≈ 19 với nền trang, ≈ 18 với thẻ — dưới 4.5² ≈ 20), nên phải tách.
- Không đặt `text-primary` trên `background` / `card`; không dùng `bg-brand` cho nút.
- Núm switch dùng `bg-primary-foreground` (luôn sáng), không dùng `bg-card`.

## 3. Layout theo bề rộng

| Bề rộng | Điều hướng | Quản trị / superadmin | Danh sách (R16) | Ô nhập | Dialog |
|---|---|---|---|---|---|
| `< md` (375) | Header có nút ☰ mở **ngăn kéo trái** (đủ menu như sidebar) + **cụm nút nổi giữa đáy**: [✨ Trợ lý] nổi bật (+ nút "Thêm nhanh" khi module đăng ký — SP3) | trong ngăn kéo | **thẻ** | 16px (iOS không zoom); ô chat không tự điền | `max-h-[90dvh]`; Thêm nhanh = bottom sheet |
| `≥ md` (768+) | **sidebar** + Header | nhóm Quản trị + "Hệ thống" (superadmin) trong sidebar; "Hệ thống" chia nhóm con gập / mở Observability · Cấu hình hệ thống · AI | **bảng** cắt chữ + Tooltip | mặc định | `max-h-[90dvh]` |

→ Một bố cục cho mỗi bề rộng, chuyển ở `md`.
- **Đã cân nhắc:** thanh tab dưới 5 mục — trong Chrome / Safari điện thoại nó chồng ngay trên thanh nút của trình duyệt thành "hai thanh 5 nút" (phản hồi thực tế ở dự án nguồn); thanh 3 mục (vẫn là thanh thứ hai).

Quy tắc:
- Cụm nút nổi (`MobileDock`): nút ≥ 48px, "Trợ lý" nền `primary` nổi bật, "Thêm nhanh" nền `brand-muted`; ẩn ở trang Trợ lý (ô nhập chat ở đáy). Thanh dính đáy của trang (vd "Xác nhận (n)") đặt trên cụm nút.
- Nội dung có `padding-bottom` = chiều cao cụm nút + `env(safe-area-inset-bottom)` (trang Trợ lý chỉ chừa safe-area).
- Chưa chạy như app (không `display-mode: standalone`) → gợi ý "Thêm vào màn hình chính" ở đầu Tổng quan (tắt được, nhớ trên máy) + mục trong ngăn kéo / menu người dùng mở hướng dẫn iPhone / Android (`InstallGuide`; Android có nút cài ngay khi Chrome cho).
- Tiêu đề trang chỉ ở Header.
- Header hiện trạng thái kết nối realtime (`SocketDot`).

## 4. Pattern màn hình

- **Danh sách (R16):**
  - từ `md`: `<table>`; ô chữ dài `max-w-[Npx]` + `<span className="block truncate">` + Radix `Tooltip` (trong `TooltipProvider delayDuration={300}`). Không dùng thuộc tính `title`.
  - dưới `md`: thẻ, không bảng cuộn ngang.
  - luôn đủ loading (skeleton) / trống (`EmptyState`) / lỗi.
- **JSON chỉ đọc (R17):** input event log, mẫu issue, trạng thái hệ thống hiện bằng `JsonView` — thu / mở từng nút, mở / gấp tất cả, copy, `maxHeight`; chuỗi không phải JSON hiện nguyên chữ.
- **Form / dialog:** label luôn hiện, lỗi cạnh field (`role="alert"`) kèm "Mã tra cứu: <cid>", nút khoá khi đang gửi.
- **Log tắt:** Event log / Issues khi API trả `enabled: false` → `LogDisabledBanner` "Ghi log đang tắt (MONGO_ENABLED=false)"; không bảng, không toast lỗi.
- **Realtime:** thay đổi của người khác / agent → toast ngắn + cập nhật đúng phần, không tải lại trang.
- **Trang có tab (Agent Studio):** nút cấp tab (Agent mới, Thêm, Thêm từ provider…) nằm **cùng hàng tab, bên phải**, không chiếm một dòng trong nội dung tab.
  - trang giữ chỗ đặt nút (`studio-actions`) cạnh `TabsList`; tab đưa nút lên bằng `TabActions` (portal) — render riêng một tab (test) thì nút hiện tại chỗ;
  - tab không có nút → chỗ đặt nút ẩn (`empty:hidden`); thứ tự nút: phụ (outline) trước, chính (đặc) ở mép phải;
  - dưới `sm`: hàng tab cuộn ngang chiếm một dòng, hàng nút ở dòng dưới, rộng hết nội dung, mỗi nút `flex-1`.
- **Màn khung cố định (chat Trợ lý):** trang không cuộn, chỉ vùng nội dung tự cuộn.
  - gốc trang `h-full min-h-0` (con trực tiếp của `<main>` — cao đúng vùng nội dung, đã trừ padding và chỗ của cụm nút nổi); mỗi tầng flex / grid ở giữa có `min-h-0`;
  - thanh công cụ trên và ô nhập ở đáy là `shrink-0`; danh sách phiên (`<ul>`) và khung tin nhắn (`chat-scroll`) là `min-h-0 flex-1 overflow-y-auto overscroll-contain`;
  - tự xuống cuối bằng `scrollTop = scrollHeight` của chính khung tin nhắn (không `scrollIntoView` — cuộn lan ra khung ngoài); màn trống (gợi ý) không tự cuộn;
  - không dùng `sticky` cho ô nhập: nó đã là phần tử cuối của cột.

## 5. Theme

| Chọn | `data-theme` trên `<html>` | Lớp CSS áp dụng |
|---|---|---|
| Sáng | `light` | `@theme` |
| Tối | `dark` | `:root[data-theme="dark"]` |
| **Theo hệ thống** (mặc định) | không đặt | `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])` khi OS tối; còn lại `@theme` |

→ Mặc định **theo hệ thống**; nút theme chỉ đổi một attribute, lựa chọn lưu ở `ui.store`.
- **Đã cân nhắc:** biến thể `dark:` của Tailwind — không khớp khi theme = hệ thống + OS tối, nên style bám token.
- Hai khối tối khai `color-scheme: dark` (`:root` khai `light`) để control gốc của trình duyệt — `<select>`, ô ngày, thanh cuộn — vẽ đúng theme.
- Meta `theme-color` tối = `background` tối (`#0E0D16`).

### 5.1 Bảng màu tối

| Phương án | Nền trang | Nút chính (nền / chữ) | Tỉ lệ chữ trên nút | Chữ nhấn | Token đổi | File component đổi | Giữ chất indigo |
|---|---|---|---|---|---|---|---|
| **Mực trung tính + nút indigo chữ trắng** | `#0E0D16` (gần đen, ánh tím rất nhạt) | `#6354F0` / trắng | 5.2 | lavender `#ADA3FF` | 42 | 7 (đổi vai `primary` / `brand`) | ✓ |
| Tím than (bản cũ của dự án nguồn) | `#120E2E`, thẻ `#1C1745` | `#A99FFF` / Ink | 8.0 | lavender (trùng nút) | 0 | 0 | ✓ nhưng ngập tím |
| Xám trung tính (zinc) | `#111114` | `#6354F0` / trắng | 5.2 | lavender | 42 | 7 | — (mất ánh thương hiệu ở mặt nền) |
| Tối ấm (than nâu, hợp Cream) | `#14120F` | `#6354F0` / trắng | 5.2 | lavender | 42 | 7 | ✗ (indigo lệch tông trên nền ấm) |

→ Chọn **mực trung tính + nút indigo chữ trắng**: mặt nền gần như trung tính nên số liệu xanh / đỏ và nút indigo nổi lên, nhìn đồng bộ với theme sáng (nút indigo chữ trắng), vẫn giữ ánh tím nhẹ của logo.
- **Đã cân nhắc:** tím than cũ — nền, thẻ, viền đều tím đậm nên mọi thứ chìm vào nhau, nút lavender pastel to bản trông bệt, chữ Cream ấm lệch tông với nền lạnh (chủ dự án chê "xấu, phối màu không phù hợp"); xám zinc — sạch nhưng mất chất thương hiệu; tối ấm — indigo và nền nâu đánh nhau.

## 6. i18n — vi / en

- `vi` mặc định, `en` dự phòng; mọi chuỗi qua `t()`; test bắt hai bộ đủ khoá.
- Số / tiền / ngày qua `Intl` theo locale + múi giờ của user (backend trả UTC).

## 7. Accessibility

- Tương phản ≥ 4.5:1 ở cả hai theme; focus luôn thấy (ring = `brand`).
- Vùng bấm ≥ 44×44px dưới `md`; nút chỉ có icon phải có `aria-label`; field có `label`.

## 8. Màn nền

| Route | Nội dung | Ai |
|---|---|---|
| `/login`, `/register` | form email / mật khẩu, Google (khi bật), logo | công khai |
| `/` | Tổng quan: lời chào, lối tắt Trợ lý / Thông báo (module thêm widget — SP3) | đăng nhập |
| `/assistant` | chat với trợ lý (màn đơn giản; superadmin có công tắc gỡ lỗi) | `agent.chat` |
| `/notifications` | thông báo, đánh dấu đã đọc | đăng nhập |
| `/profile` | hồ sơ, đổi mật khẩu | đăng nhập |
| `/admin/users` | danh sách user; khoá / mở, gán role, đặt lại mật khẩu (cần `user.manage`) | `user.view` |
| `/admin/roles` | role có sẵn (chỉ xem) + role tự tạo | `role.manage` |
| `/sa/status` | trạng thái (`JsonView`) + thẻ gửi thông báo thử | superadmin |
| `/sa/events`, `/sa/issues` | event log, issues (banner khi tắt Mongo) | superadmin |
| `/sa/settings` | cài đặt hệ thống | superadmin |
| `/studio`, `/sa/traces`, `/sa/usage`, `/sa/chat-guard` | Agent Studio, trace, usage, chống spam | superadmin |
| `/403` | không có quyền | — |

## 9. Checklist trước khi giao UI

- [ ] 375 / 768 / 1024 / 1440: `document.documentElement.scrollWidth <= innerWidth`
- [ ] Dưới `md` danh sách là thẻ; từ `md` bảng có ô cắt chữ + Tooltip, không `title` (R16)
- [ ] JSON chỉ đọc qua `JsonView` (R17)
- [ ] Cụm nút nổi đáy không che nội dung cuối trang; dialog ≤ 90dvh
- [ ] Màn khung cố định (chat): `main.scrollHeight <= main.clientHeight`; chỉ danh sách / khung tin nhắn cuộn; ô nhập không bị thanh tab che
- [ ] Vùng bấm ≥ 44px; focus thấy được bằng bàn phím
- [ ] Icon lucide, không emoji; transition 150–300ms
- [ ] Tương phản ≥ 4.5:1 cả hai theme
- [ ] 0 màu hard-code, 0 chuỗi ngoài từ điển, parity vi / en
- [ ] E2E Playwright qua subagent Sonnet (R22) ở 375 + 1440, console error = 0

---

*Cập nhật: 2026-10-13*
