"""`bw seed-test-users` — 2 tenant + user test cho dev / E2E; không chạy ở prod; chạy lại không tạo trùng."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.engine import make_url
from sqlmodel import select

from app.auth.models import UserRole
from app.auth.passwords import hash_password
from app.auth.rbac import role_by_name
from app.auth.superadmins import apply_superadmin
from app.auth.users import create_user, user_by_email
from app.core.connections.postgres import Postgres
from app.core.logging import get_logger
from app.core.settings import Settings
from app.tenants.models import DEFAULT_TENANT_SLUG, Tenant

logger = get_logger(__name__)

SUPERADMIN_SEED_EMAIL = "superadmin@test.local"
SEED_DB_SUFFIXES = ("_test", "_e2e", "_dev")  # chỉ DB dùng thử — DB thật dùng chung với dev (D19)
ACME_SLUG = "acme"  # tenant thứ hai của dữ liệu thử — luôn kiểm được việc tách dữ liệu (D11)
# (email, tên, tenant slug, role)
SEED_USERS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (SUPERADMIN_SEED_EMAIL, "Superadmin", DEFAULT_TENANT_SLUG, ("member",)),
    ("admin@test.local", "Admin", DEFAULT_TENANT_SLUG, ("admin",)),
    ("user1@test.local", "User 1", DEFAULT_TENANT_SLUG, ("member",)),
    ("user2@test.local", "User 2", DEFAULT_TENANT_SLUG, ("member",)),
    ("user3@test.local", "User 3", DEFAULT_TENANT_SLUG, ("viewer",)),
    ("acme-admin@test.local", "Acme Admin", ACME_SLUG, ("admin",)),
    ("acme1@test.local", "Acme 1", ACME_SLUG, ("member",)),
)


async def _tenant(session, slug: str) -> Tenant:
    tenant = (await session.exec(select(Tenant).where(Tenant.slug == slug))).first()
    if tenant is None:
        tenant = Tenant(name=slug.title(), slug=slug)
        session.add(tenant)
        await session.flush()
    return tenant


async def seed_users(session, settings: Settings) -> list[dict]:
    """Tạo tenant + user còn thiếu; user đã có → mật khẩu = SEED_PASSWORD, mở khoá, đã xác thực email, đủ role."""
    password_hash = hash_password(settings.SEED_PASSWORD)
    out: list[dict] = []
    for email, name, slug, roles in SEED_USERS:
        tenant = await _tenant(session, slug)
        user = await user_by_email(session, email)
        created = user is None
        if user is None:
            user = await create_user(
                session,
                settings,
                email=email,
                name=name,
                password_hash=password_hash,
                tenant_id=tenant.id,
                role=roles[0],
                verified=True,
            )
        else:
            user.password_hash, user.is_active, user.must_change_password = password_hash, True, False
            user.email_verified_at = user.email_verified_at or datetime.now(UTC)
            apply_superadmin(user, settings)
            session.add(user)
        for role_name in roles:
            role = await role_by_name(session, role_name)
            if await session.get(UserRole, (user.id, role.id)) is None:
                session.add(UserRole(user_id=user.id, role_id=role.id))
        await session.flush()
        out.append(
            {"email": email, "tenant": slug, "created": created, "superadmin": user.is_superadmin, "roles": list(roles)}
        )
    return out


def seed_target_problem(settings: Settings) -> str | None:
    """Lý do từ chối seed (None = được chạy): ENV=prod, hoặc DB đích không phải DB dùng thử (tên có hậu tố
    `SEED_DB_SUFFIXES`) — tài khoản admin mật khẩu chung không được vào dữ liệu thật."""
    if settings.is_prod:
        return "seed-test-users không chạy ở môi trường prod"
    database = make_url(settings.POSTGRES_RW_URL).database or ""
    if not database.endswith(SEED_DB_SUFFIXES):
        suffixes = "/".join(SEED_DB_SUFFIXES)
        return f"seed-test-users chỉ chạy trên DB dùng thử ({suffixes}) — DB '{database}' là dữ liệu thật"
    return None


async def seed_test_users(settings: Settings) -> list[dict]:
    problem = seed_target_problem(settings)
    if problem:
        raise RuntimeError(problem)
    if SUPERADMIN_SEED_EMAIL not in settings.superadmin_emails:
        logger.warning(
            "%s không có trong SUPERADMIN_EMAILS — tài khoản này chỉ là user thường",
            SUPERADMIN_SEED_EMAIL,
            extra={"loc": "auth0402"},
        )
    pg = Postgres(settings)
    try:
        async with pg.rw() as session:
            rows = await seed_users(session, settings)
    finally:
        await pg.close()
    defaults = [] if "SEED_PASSWORD" in settings.model_fields_set else ["SEED_PASSWORD"]
    logger.info(
        "seed user test: %s DEFAULTS_APPLIED=%s",
        [r["email"] for r in rows],
        defaults,
        extra={"loc": "auth0007"},
    )
    return rows
