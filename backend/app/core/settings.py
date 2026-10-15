"""Cấu hình ứng dụng — một nguồn duy nhất, đọc từ biến môi trường + `.env` ở gốc repo."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/settings.py → parents[3] = gốc repo
ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Service ──
    PROJECT_NAME: str = "BizWithAgents"
    SERVICE_NAME: str = "bizwithagents-backend"
    SERVICE_PATH: str = "bizwithagents"
    ENV: str = "dev"
    DEBUG: bool = False
    APP_TIMEZONE: str = "Asia/Ho_Chi_Minh"
    BUILD_VERSION: str = "dev"  # commit đang chạy — compose truyền SOURCE_COMMIT của Coolify nếu có

    # ── HTTP ──
    HOST: str = "0.0.0.0"
    PORT: int = 8202
    WORKERS: int = 1
    CORS_ALLOW_ORIGINS: list[str] = ["http://localhost:8201"]

    # ── Logging ──
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    LOG_LIB_LEVEL: str = "WARNING"
    LOG_HTTP_IN: bool = True
    LOG_HTTP_OUT: bool = True
    LOG_HTTP_RULES_FILE: str = ""  # YAML rule log body / header theo đường dẫn; trống = chỉ metadata
    LOG_HTTP_SLOW_MS: int = 1000
    LOG_REDACT_KEYS: str = ""

    # ── Postgres (psycopg3) — 2 kênh ──
    POSTGRES_RW_URL: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/bizwithagents"
    POSTGRES_RO_URL: str = ""
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
    POSTGRES_RO_POOL_SIZE: int = 0
    POSTGRES_POOL_RECYCLE: int = 1800
    POSTGRES_POOL_PRE_PING: bool = True
    POSTGRES_RW_MAX_RETRIES: int = 2
    POSTGRES_STATEMENT_TIMEOUT: int = 30
    POSTGRES_PGBOUNCER: bool = False

    # ── MongoDB — chỉ ghi log; tắt bằng MONGO_ENABLED ──
    MONGO_ENABLED: bool = True
    MONGO_RW_URL: str = ""
    MONGO_RO_URL: str = ""
    MONGO_DB_NAME: str = "bizwithagents"

    # ── Redis (cache / KV) — 2 kênh; mọi key có tiền tố bw: ──
    REDIS_RW_URL: str = "redis://127.0.0.1:6379/10"
    REDIS_RO_URL: str = ""

    # ── RabbitMQ — mọi messaging ──
    RABBITMQ_URL: str = ""
    SCHEDULER_LEADER_TTL: int = 15  # giây
    SCHEDULER_LEADER_KEY: str = "bw:leader:schedule"
    HEARTBEAT_INTERVAL: float = 15.0  # giây — nhịp tim process nền
    REALTIME_EVENT_MAX_AGE: float = 60.0

    # ── Auth ──
    AUTH_ALGORITHM: str = "EdDSA"
    AUTH_PRIVATE_KEY_FILE: str = ""
    AUTH_PUBLIC_KEY_FILE: str = ""
    AUTH_PRIVATE_KEY: str = ""
    AUTH_PUBLIC_KEY: str = ""
    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    AUTH_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    AUTH_PASSWORD_MIN_LENGTH: int = 8
    AUTH_LOGIN_RATE_LIMIT: int = 5
    AUTH_REGISTER_RATE_LIMIT: int = 10  # lần đăng ký / IP / cửa sổ
    AUTH_REGISTER_RATE_WINDOW: int = 3600  # giây
    AUTH_REFRESH_REUSE_GRACE_SECONDS: int = 10  # hai tab refresh cùng lúc: tab thua không làm mất phiên
    AUTH_VERIFY_TOKEN_HOURS: int = 24  # link xác thực email (D14)
    AUTH_RESET_TOKEN_MINUTES: int = 60  # link đặt lại mật khẩu
    AUTH_EMAIL_RATE_LIMIT: int = 5  # thư xác thực / quên mật khẩu mỗi giờ theo IP + email
    SEED_PASSWORD: str = "password123"  # bw seed-test-users (chỉ dev / E2E)
    SUPERADMIN_EMAILS: str = ""  # nguồn sự thật của superadmin
    CREDENTIAL_KEYS: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    FRONTEND_AUTH_CALLBACK_URL: str = ""
    # ── Mail (D14) — `console` (mặc định: log + hộp thư /sa/mail) | `smtp` ──
    MAIL_TRANSPORT: str = "console"
    MAIL_FROM: str = "BizWithAgents <no-reply@bizwithagents.local>"
    MAIL_OUTBOX_MAX: int = 50
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_STARTTLS: bool = True
    SMTP_SSL: bool = False
    SMTP_TIMEOUT: float = 20.0
    # URL công khai trình duyệt thấy (https — TLS kết thúc ở Cloudflare). Có giá trị → dựng 2 URL callback ở trên từ nó,
    # thay cho domain `http://` của Coolify (`SERVICE_URL_BW_WEB`) — đổi domain sang https sẽ dính Force HTTPS.
    PUBLIC_URL: str = ""

    @field_validator("AUTH_PRIVATE_KEY", "AUTH_PUBLIC_KEY")
    @classmethod
    def _pem_multiline(cls, value: str) -> str:
        """PEM dán vào env có khi thành một dòng với `\\n` (`bw keys --print`), có khi bị escape thêm
        thành `\\\\n` (Coolify) — đưa về nhiều dòng. PEM không bao giờ chứa `\\` nên bỏ mọi `\\` còn sót."""
        return re.sub(r"\\+n", "\n", value.strip()).replace("\\", "")

    @model_validator(mode="after")
    def _public_callbacks(self) -> Settings:
        base = self.PUBLIC_URL.strip().rstrip("/")
        if base:
            self.GOOGLE_REDIRECT_URI = f"{base}/{self.SERVICE_PATH}/api/auth/google/callback"
            self.FRONTEND_AUTH_CALLBACK_URL = f"{base}/auth/callback"
        return self

    @property
    def postgres_ro_url(self) -> str:
        return self.POSTGRES_RO_URL or self.POSTGRES_RW_URL

    @property
    def mongo_ro_url(self) -> str:
        return self.MONGO_RO_URL or self.MONGO_RW_URL

    @property
    def redis_ro_url(self) -> str:
        return self.REDIS_RO_URL or self.REDIS_RW_URL

    @property
    def postgres_ro_pool_size(self) -> int:
        return self.POSTGRES_RO_POOL_SIZE or self.POSTGRES_POOL_SIZE

    @property
    def api_prefix(self) -> str:
        return f"/{self.SERVICE_PATH}/api"

    @property
    def superadmin_emails(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.SUPERADMIN_EMAILS.split(",") if e.strip())

    @property
    def is_prod(self) -> bool:
        return self.ENV in {"staging", "prod", "production"}

    @property
    def extra_redact_keys(self) -> frozenset[str]:
        return frozenset(k.strip().lower() for k in self.LOG_REDACT_KEYS.split(",") if k.strip())

    def resolve_path(self, value: str) -> Path | None:
        """Đường dẫn cấu hình tương đối được hiểu là tính từ gốc repo."""
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else ROOT_DIR / path

    def config_problems(self) -> list[str]:
        """Thiếu / sai cấu hình bắt buộc — `bw check-config` và `bw migrate` dừng ngay khi có."""
        out: list[str] = []
        for name in ("POSTGRES_RW_URL", "REDIS_RW_URL", "RABBITMQ_URL"):
            if not getattr(self, name).strip():
                out.append(f"{name} chưa cấu hình")
        if self.MONGO_ENABLED and not (self.MONGO_RW_URL.strip() and self.MONGO_DB_NAME.strip()):
            out.append("MONGO_ENABLED=true nhưng thiếu MONGO_RW_URL / MONGO_DB_NAME (hoặc đặt MONGO_ENABLED=false)")
        if bool(self.AUTH_PRIVATE_KEY) != bool(self.AUTH_PUBLIC_KEY):
            out.append("AUTH_PRIVATE_KEY và AUTH_PUBLIC_KEY phải đặt cùng nhau")
        if not self.AUTH_PRIVATE_KEY and not (self.AUTH_PRIVATE_KEY_FILE and self.AUTH_PUBLIC_KEY_FILE):
            out.append("chưa có khoá JWT: đặt AUTH_PRIVATE_KEY_FILE + AUTH_PUBLIC_KEY_FILE hoặc PEM trong env")
        if self.is_prod and not self.superadmin_emails:
            out.append("SUPERADMIN_EMAILS bắt buộc ở môi trường prod")
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()


_active: Settings | None = None


def use_settings(settings: Settings | None) -> None:
    """Settings của process hiện tại (create_app / launcher đặt)."""
    global _active
    _active = settings


def active_settings() -> Settings:
    return _active if _active is not None else get_settings()
