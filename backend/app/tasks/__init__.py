"""Module mẫu Tasks (template-v1 §3.6): công việc của một tổ chức — làm được bằng web và bằng trợ lý."""

from app.tasks import errors as errors  # noqa: F401 — đăng ký mã lỗi
from app.tasks import notify as notify  # noqa: F401 — đăng ký loại thông báo
from app.tasks import permissions as permissions  # noqa: F401 — khai quyền tasks.*
