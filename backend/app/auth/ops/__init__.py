"""Op miền auth (auth.* · admin.* · rbac.*) — nạp gói = đăng ký op, catalog quyền, bước sau migrate."""

import app.auth.rbac  # noqa: F401
import app.auth.superadmins  # noqa: F401
from app.auth.ops import admin, auth, email, policies, rbac  # noqa: F401, E402
