"""In các dòng `export KEY=…` cho stack chạy thử (`scripts/dev_stack.sh`).

Cùng máy chủ DB / broker với `.env` nhưng tách khỏi dữ liệu thật: Postgres / Mongo / vhost `bizwithagents_e2e`,
Redis db 12, khoá JWT riêng trong thư mục chạy, superadmin là tài khoản seed. Mật khẩu chỉ đi qua `eval` của script,
không in ra màn hình.

Dùng: PYTHONPATH=backend backend/.venv/bin/python scripts/stack_env.py <thư mục khoá>
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from app.core.settings import Settings

NAMESPACE = "bizwithagents_e2e"
REDIS_DB = 12  # dev / prod 10, test 11 (D19)
SUPERADMIN = "superadmin@test.local"
WEB_URL = f"http://127.0.0.1:{os.environ.get('FRONTEND_PORT', '8201')}"  # cửa web của stack (scripts/dev_stack.sh)


def _swap_tail(url: str, tail: str) -> str:
    """`scheme://…/<cũ>` → `scheme://…/<tail>` (tên DB / vhost / số db Redis nằm sau dấu `/` cuối)."""
    return url.rsplit("/", 1)[0] + "/" + tail


def stack_env(settings: Settings, keys_dir: Path) -> dict[str, str]:
    return {
        "ENV": "dev",  # devtools bật, seed được
        "DEBUG": "false",
        "POSTGRES_RW_URL": _swap_tail(settings.POSTGRES_RW_URL, NAMESPACE),
        "POSTGRES_RO_URL": "",
        "REDIS_RW_URL": _swap_tail(settings.REDIS_RW_URL, str(REDIS_DB)),
        "REDIS_RO_URL": "",
        "RABBITMQ_URL": _swap_tail(settings.RABBITMQ_URL, NAMESPACE),
        "MONGO_DB_NAME": NAMESPACE,
        "MONGO_RO_URL": "",
        # khoá riêng: token stack thử ký không bao giờ hợp lệ ở bản deploy (khoá .env dùng chung với prod)
        "AUTH_PRIVATE_KEY": "",
        "AUTH_PUBLIC_KEY": "",
        "AUTH_PRIVATE_KEY_FILE": str(keys_dir / "jwt_private.pem"),
        "AUTH_PUBLIC_KEY_FILE": str(keys_dir / "jwt_public.pem"),
        "SUPERADMIN_EMAILS": SUPERADMIN,
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
        # thư chỉ vào outbox Redis (smoke đọc link mời / đặt lại mật khẩu ở đó); link trỏ về web của stack
        "MAIL_TRANSPORT": "console",
        "PUBLIC_URL": WEB_URL,
        # khoá credential cố định của stack thử: mọi process (api / consume / work) phải giải mã chéo được
        "CREDENTIAL_KEYS": credential_key(keys_dir),
    }


def credential_key(keys_dir: Path) -> str:
    path = keys_dir / "credential.key"
    if not path.exists():
        keys_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(Fernet.generate_key().decode(), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


def main() -> int:
    if len(sys.argv) != 2:
        print("dùng: stack_env.py <thư mục khoá>", file=sys.stderr)
        return 2
    keys_dir = Path(sys.argv[1]).resolve()
    for key, value in stack_env(Settings(), keys_dir).items():
        print(f"export {key}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
