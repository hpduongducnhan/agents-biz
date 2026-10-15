"""Link trong thư trỏ về frontend: `PUBLIC_URL` → origin của `FRONTEND_AUTH_CALLBACK_URL` → `CORS_ALLOW_ORIGINS[0]`.
Đang dùng dự phòng thì cảnh báo một lần (R11)."""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit

from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger(__name__)
_warned: set[str] = set()


def _origin(url: str) -> str:
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def app_base_url(settings: Settings) -> str:
    if settings.PUBLIC_URL.strip():
        return settings.PUBLIC_URL.strip().rstrip("/")
    for source, url in (
        ("FRONTEND_AUTH_CALLBACK_URL", settings.FRONTEND_AUTH_CALLBACK_URL),
        ("CORS_ALLOW_ORIGINS", settings.CORS_ALLOW_ORIGINS[0] if settings.CORS_ALLOW_ORIGINS else ""),
    ):
        origin = _origin(url)
        if origin:
            if source not in _warned:
                _warned.add(source)
                logger.warning(
                    "link trong thư dùng %s=%s (chưa đặt PUBLIC_URL); DEFAULTS_APPLIED=[app_base_url]",
                    source,
                    origin,
                    extra={"loc": "mail0006"},
                )
            return origin
    return ""


def app_link(settings: Settings, path: str, **query: str) -> str:
    qs = f"?{urlencode(query)}" if query else ""
    return f"{app_base_url(settings)}{path}{qs}"
