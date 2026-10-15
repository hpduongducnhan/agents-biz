"""Superadmin = email trong SUPERADMIN_EMAILS: đồng bộ ở `bw migrate` và ở mỗi lần đăng nhập / refresh."""

from __future__ import annotations

from sqlalchemy import func, update

from app.auth.models import User
from app.core.logging import get_logger
from app.core.migrate import post_migrate_step
from app.core.settings import Settings

logger = get_logger(__name__)


def apply_superadmin(user: User, settings: Settings) -> bool:
    """Đặt `user.is_superadmin` theo env (chưa flush). Trả True nếu cờ vừa đổi."""
    want = user.email.strip().lower() in settings.superadmin_emails
    if user.is_superadmin == want:
        return False
    user.is_superadmin = want
    logger.info("cờ superadmin user=%s → %s theo SUPERADMIN_EMAILS", user.id, want, extra={"loc": "auth0004"})
    return True


@post_migrate_step("auth.superadmins", order=20)
async def sync_superadmins(session, settings: Settings) -> dict[str, list[str]]:
    """Có trong env → bật cờ; không có → tắt (so chữ thường — env đã chuẩn hoá ở `Settings.superadmin_emails`)."""
    emails = sorted(settings.superadmin_emails)
    if not emails:
        logger.warning(
            "SUPERADMIN_EMAILS trống — không ai là superadmin DEFAULTS_APPLIED=['SUPERADMIN_EMAILS']",
            extra={"loc": "auth0403"},
        )
    listed = func.lower(User.email).in_(emails)
    out: dict[str, list[str]] = {}
    for key, where, value in (("promoted", listed, True), ("demoted", ~listed, False)):
        stmt = (
            update(User)
            .where(where, User.is_superadmin.is_(not value))
            .values(is_superadmin=value)
            .returning(User.email)
            .execution_options(synchronize_session=False)
        )
        out[key] = sorted(row[0] for row in (await session.exec(stmt)).all())
    logger.info(
        "superadmin hiệu lực: env=%d email, promoted=%s, demoted=%s",
        len(emails),
        out["promoted"],
        out["demoted"],
        extra={"loc": "auth0005"},
    )
    return out
