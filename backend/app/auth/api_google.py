"""GET /auth/google/authorize · /auth/google/callback — redirect trình duyệt; token về FE qua fragment."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from app.auth.flags import AuthFlags, auth_flags
from app.auth.google import GoogleOAuth, GoogleProfile
from app.auth.models import OAuthAccount, User
from app.auth.sessions import issue_session
from app.auth.signin import check_can_sign_in
from app.auth.superadmins import apply_superadmin
from app.auth.users import normalize_email, user_by_email
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.operations.spec import ui_only
from app.core.rkeys import rkey
from app.core.settings import Settings, active_settings
from app.tenants.enroll import enroll

logger = get_logger(__name__)
router = APIRouter(prefix="/auth/google", tags=["auth"])
STATE_TTL = 600


def _state_key(state: str) -> str:
    return rkey("auth", "oauth", state)


def _front(**params: str) -> RedirectResponse:
    return RedirectResponse(f"{active_settings().FRONTEND_AUTH_CALLBACK_URL}#{urlencode(params)}", status_code=302)


async def _enabled_flags(settings: Settings) -> AuthFlags:
    async with get_connections().postgres.ro() as db:
        flags = await auth_flags(db, settings)
    if not flags.google:
        raise AppException(2108, status_code=400)
    return flags


@router.get("/authorize")
@ui_only("redirect trình duyệt sang Google — không phải lời gọi dữ liệu")
async def google_authorize() -> RedirectResponse:
    s = active_settings()
    await _enabled_flags(s)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    await get_connections().redis.rw.set(_state_key(state), verifier, ex=STATE_TTL)
    return RedirectResponse(GoogleOAuth(s).authorize_url(state, verifier), status_code=302)


async def google_user(db, profile: GoogleProfile, *, settings: Settings) -> User:
    """User theo Google sub → theo email → tạo mới theo lời mời gắn email / `signup_mode` (D12; đóng → 2105).
    Email Google đã xác minh nên user mới coi như đã xác thực email."""
    email = normalize_email(profile.email)
    stmt = select(OAuthAccount).where(OAuthAccount.provider == "google", OAuthAccount.provider_uid == profile.sub)
    account = (await db.exec(stmt)).first()
    user = await db.get(User, account.user_id) if account else await user_by_email(db, email)
    if user is None:
        user = await enroll(db, settings, email=email, name=profile.name, verified=True, allow_email_invite=True)
    if account is None:
        db.add(OAuthAccount(user_id=user.id, provider="google", provider_uid=profile.sub, email=email))
    return user


@router.get("/callback")
@ui_only("Google redirect về — đổi code lấy hồ sơ rồi redirect FE kèm token")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    s = active_settings()
    await _enabled_flags(s)
    verifier = await get_connections().redis.rw.getdel(_state_key(state)) if state else None
    if not verifier:
        raise AppException(2108, status_code=400, detail="Invalid or expired OAuth state")
    if error or not code:
        return _front(error="google_denied")
    try:
        profile = await GoogleOAuth(s).exchange(code, verifier)
    except AppException as exc:  # email Google chưa xác minh
        logger.warning("Google từ chối hồ sơ: %s", exc.code, extra={"loc": "auth0404"})
        return _front(error=str(exc.code))
    except Exception as exc:  # noqa: BLE001 — lỗi phía Google → báo FE thay vì trang 500
        logger.warning("đổi code Google lỗi: %s", exc, extra={"loc": "auth0501"})
        return _front(error="google_failed")
    try:
        async with get_connections().postgres.rw() as db:
            user = await google_user(db, profile, settings=s)
            if not user.is_active:
                raise AppException(2103, status_code=403)
            apply_superadmin(user, s)
            await check_can_sign_in(db, s, user)
            user.last_login_at = datetime.now(UTC)
            db.add(user)
            tokens = await issue_session(db, user, settings=s, ip=request.client.host if request.client else None)
    except AppException as exc:  # đăng ký đóng, tenant khoá / đầy, chưa xác thực… → FE hiện lỗi theo mã
        return _front(error=str(exc.code))
    return _front(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=str(tokens.expires_in),
    )
