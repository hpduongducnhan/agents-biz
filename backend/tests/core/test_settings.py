"""Settings: mặc định của BizWithAgents, superadmin từ env, cờ Mongo, kiểm cấu hình."""

from app.auth.flags import google_missing
from app.core.settings import Settings


def make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_defaults_are_bizwithagents():
    s = make()
    assert s.SERVICE_PATH == "bizwithagents" and s.api_prefix == "/bizwithagents/api"
    assert s.PORT == 8202 and s.MONGO_ENABLED is True and s.MONGO_DB_NAME == "bizwithagents"
    assert s.SCHEDULER_LEADER_KEY.startswith("bw:")


def test_ro_urls_fall_back_to_rw():
    s = make(POSTGRES_RW_URL="postgresql+psycopg://a@h/db", REDIS_RW_URL="redis://h/6", MONGO_RW_URL="mongodb://h")
    assert s.postgres_ro_url == s.POSTGRES_RW_URL and s.redis_ro_url == s.REDIS_RW_URL
    assert s.mongo_ro_url == "mongodb://h"
    assert make(MONGO_RO_URL="mongodb://r", MONGO_RW_URL="mongodb://h").mongo_ro_url == "mongodb://r"


def test_superadmin_emails_are_normalised():
    s = make(SUPERADMIN_EMAILS=" A@x.com, b@Y.com ,,a@x.com ")
    assert s.superadmin_emails == frozenset({"a@x.com", "b@y.com"})
    assert make().superadmin_emails == frozenset()


def _ok(**kw) -> Settings:
    base = {
        "POSTGRES_RW_URL": "postgresql+psycopg://a@h/bizwithagents",
        "REDIS_RW_URL": "redis://h/6",
        "RABBITMQ_URL": "amqp://u:p@h/bizwithagents",
        "MONGO_RW_URL": "mongodb://h",
        "AUTH_PRIVATE_KEY_FILE": "/keys/p.pem",
        "AUTH_PUBLIC_KEY_FILE": "/keys/q.pem",
        "SUPERADMIN_EMAILS": "root@x.com",
    }
    return make(**(base | kw))


def test_config_problems_empty_when_complete():
    assert _ok().config_problems() == []


def test_mongo_url_required_only_when_enabled():
    assert any("MONGO_RW_URL" in p for p in _ok(MONGO_RW_URL="").config_problems())
    assert _ok(MONGO_ENABLED=False, MONGO_RW_URL="").config_problems() == []


def test_missing_broker_and_half_keys_are_reported():
    problems = _ok(RABBITMQ_URL="", AUTH_PRIVATE_KEY="x").config_problems()
    assert any("RABBITMQ_URL" in p for p in problems)
    assert any("AUTH_PRIVATE_KEY" in p for p in problems)


def test_prod_requires_superadmins():
    assert any("SUPERADMIN_EMAILS" in p for p in _ok(ENV="prod", SUPERADMIN_EMAILS="").config_problems())
    assert _ok(ENV="dev", SUPERADMIN_EMAILS="").config_problems() == []


def test_resolve_path_relative_to_repo_root(tmp_path):
    s = make()
    assert s.resolve_path("") is None
    assert s.resolve_path(str(tmp_path)) == tmp_path
    assert s.resolve_path(".secrets/a.pem").parts[-2:] == (".secrets", "a.pem")


def test_http_log_defaults():
    s = make()
    assert (s.LOG_HTTP_IN, s.LOG_HTTP_OUT, s.LOG_HTTP_SLOW_MS, s.LOG_HTTP_RULES_FILE) == (True, True, 1000, "")


def test_auth_defaults_follow_spec():
    s = make()
    assert (s.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES, s.AUTH_REFRESH_TOKEN_EXPIRE_DAYS, s.AUTH_PASSWORD_MIN_LENGTH) == (
        30,
        7,
        8,
    )
    assert (s.AUTH_LOGIN_RATE_LIMIT, s.AUTH_REGISTER_RATE_LIMIT, s.AUTH_REGISTER_RATE_WINDOW) == (5, 10, 3600)
    assert s.AUTH_REFRESH_REUSE_GRACE_SECONDS == 10 and s.SEED_PASSWORD == "password123"


CB = "/bizwithagents/api/auth/google/callback"


def test_public_url_overrides_callbacks():
    s = make(
        PUBLIC_URL="https://app.example.com",
        GOOGLE_REDIRECT_URI="http://old/cb",
        FRONTEND_AUTH_CALLBACK_URL="http://old/f",
    )
    assert s.GOOGLE_REDIRECT_URI == "https://app.example.com" + CB
    assert s.FRONTEND_AUTH_CALLBACK_URL == "https://app.example.com/auth/callback"


def test_public_url_trailing_slash_and_spaces_are_stripped():
    for raw in ("https://app.example.com/", "  https://app.example.com/  ", "https://app.example.com//"):
        s = make(PUBLIC_URL=raw)
        assert s.GOOGLE_REDIRECT_URI == "https://app.example.com" + CB, raw
        assert s.FRONTEND_AUTH_CALLBACK_URL == "https://app.example.com/auth/callback", raw


def test_public_url_uses_custom_service_path():
    s = make(PUBLIC_URL="https://h.io", SERVICE_PATH="wallet")
    assert s.GOOGLE_REDIRECT_URI == "https://h.io/wallet/api/auth/google/callback"
    assert s.FRONTEND_AUTH_CALLBACK_URL == "https://h.io/auth/callback"


def test_empty_public_url_keeps_explicit_callbacks():
    s = make(GOOGLE_REDIRECT_URI="http://x/cb", FRONTEND_AUTH_CALLBACK_URL="http://x/front")
    assert (s.GOOGLE_REDIRECT_URI, s.FRONTEND_AUTH_CALLBACK_URL) == ("http://x/cb", "http://x/front")
    blank = make(PUBLIC_URL="   ", GOOGLE_REDIRECT_URI="http://x/cb", FRONTEND_AUTH_CALLBACK_URL="http://x/front")
    assert (blank.GOOGLE_REDIRECT_URI, blank.FRONTEND_AUTH_CALLBACK_URL) == ("http://x/cb", "http://x/front")
    assert make().PUBLIC_URL == ""


def test_public_url_satisfies_google_redirect_requirement():
    only_public = make(GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="secret", PUBLIC_URL="https://h.io")
    assert google_missing(only_public) == ()
    assert google_missing(make(GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="secret")) == ("GOOGLE_REDIRECT_URI",)
