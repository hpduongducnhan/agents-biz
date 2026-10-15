"""Công tắc auth đang hiệu lực: chế độ đăng ký (`signup_mode` — D12), xác thực email (D14) và đăng nhập Google
(env Google + công tắc `google_enabled`)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.core.settings import Settings
from app.system import settings_store

logger = get_logger(__name__)
GOOGLE_KEYS = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")


@dataclass(frozen=True)
class AuthFlags:
    signup_mode: str  # default_tenant | new_tenant | invite_only
    email_verification: str  # off | soft | required
    google: bool
    google_missing: tuple[str, ...]  # key env Google còn trống → Google tắt dù công tắc bật

    @property
    def signup_open(self) -> bool:
        """Có tự đăng ký (không lời mời) được không."""
        return self.signup_mode != "invite_only"


_last: AuthFlags | None = None


def google_missing(settings: Settings) -> tuple[str, ...]:
    return tuple(key for key in GOOGLE_KEYS if not getattr(settings, key).strip())


async def auth_flags(session, settings: Settings) -> AuthFlags:
    """Giá trị hiệu lực; khác lần trước trong process → log `auth0008` kèm DEFAULTS_APPLIED."""
    global _last
    system = await settings_store.get_system_settings(session)
    missing = google_missing(settings)
    flags = AuthFlags(
        signup_mode=system.signup_mode,
        email_verification=system.email_verification,
        google=not missing and bool(system.google_enabled),
        google_missing=missing,
    )
    if flags != _last:
        _last = flags
        logger.info(
            "auth hiệu lực: signup_mode=%s email_verification=%s google=%s (google_enabled=%s) DEFAULTS_APPLIED=%s",
            flags.signup_mode,
            flags.email_verification,
            flags.google,
            bool(system.google_enabled),
            list(missing),
            extra={"loc": "auth0008"},
        )
    return flags
