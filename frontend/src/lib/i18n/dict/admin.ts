import type { Pairs } from "../pairs";

export const admin: Pairs = {
  "admin.users.search": ["Tìm theo tên hoặc email…", "Search by name or email…"],
  "admin.users.empty": ["Không có người dùng khớp", "No matching users"],
  "admin.users.col.name": ["Tên", "Name"],
  "admin.users.col.status": ["Trạng thái", "Status"],
  "admin.users.col.lastLogin": ["Đăng nhập gần nhất", "Last sign-in"],
  "admin.users.roles": ["Role hệ thống", "System roles"],
  "admin.users.edit": ["Sửa người dùng", "Edit user"],
  "admin.users.reset": ["Đặt lại mật khẩu", "Reset password"],
  "admin.users.resetHint": ["Tối thiểu 8 ký tự — người dùng phải đổi ở lần đăng nhập sau", "At least 8 characters — the user must change it at next sign-in"],
  "admin.users.resetDone": ["Đã đặt lại mật khẩu cho {email}", "Password reset for {email}"],
  "admin.users.saved": ["Đã lưu người dùng", "User saved"],
  "admin.users.active": ["Tài khoản đang hoạt động", "Account active"],
  "admin.users.activeBadge": ["Hoạt động", "Active"],
  "admin.users.disabled": ["Đã khoá", "Disabled"],
  "admin.users.mustChange": ["Phải đổi mật khẩu", "Must change password"],
  "admin.users.selfHint": ["Bạn không thể tự khoá chính mình", "You cannot disable yourself"],
  "admin.users.superadminHint": ["Superadmin do cấu hình máy chủ (SUPERADMIN_EMAILS) quản lý — không bật / tắt ở đây", "Superadmin is managed by server config (SUPERADMIN_EMAILS) — not editable here"],
};
