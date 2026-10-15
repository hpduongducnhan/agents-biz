"""Fixture dùng chung cho test backend BizWithAgents."""

import asyncio
import io
import json
import logging
from types import SimpleNamespace

import aio_pika
import httpx2
import psycopg
import pytest
import redis
from alembic.script import ScriptDirectory
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.routing import APIRoute

import app.auth.ops  # noqa: F401 — cài principal resolver lúc import; autouse khôi phục sau test đặt None
import app.notifications.ops  # noqa: F401 — cài notifier lúc import
from app.auth.tokens import configure_tokens
from app.core.cid import _cid, get_cid, new_cid
from app.core.connections.registry import close_connections, get_connections, init_connections
from app.core.logging import LOGGER_NAME, CidFilter, JsonFormatter
from app.core.messaging.hub import MessagingHub, set_hub
from app.core.migrate import alembic_config, run_migrations, run_post_migrate
from app.core.operations import runner
from app.core.security import principal as principal_mod
from app.core.settings import Settings, get_settings, use_settings
from app.domains import load_domains
from app.main import create_app
from app.observability.sinks import Sinks, noop_sinks, set_sinks
from tests.auth.api import Api
from tests.fixtures.fx import ops as fx_ops
from tests.fixtures.sinks import MemoryEventLog, MemoryIssues

TEST_REDIS_DB = "11"
# fixture nối hạ tầng thật — test dùng (trực tiếp hay gián tiếp) tự mang marker `integration`
INFRA_FIXTURES = frozenset({"messaging_env", "op_env", "app_env", "plain_stack", "mongo_stack", "stack", "pg"})


def pytest_collection_modifyitems(items) -> None:
    """`pytest -m "not integration"` chạy được khi chưa có hạ tầng (app mới vừa `make new-app`)."""
    for item in items:
        if INFRA_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(autouse=True)
def clean_cid():
    """`set_cid` trong test đồng bộ ghi vào context chính → rò sang test sau; mỗi test bắt đầu không cid."""
    _cid.set(None)


@pytest.fixture(autouse=True)
def restore_global_hooks():
    """Resolver principal / notifier do miền cài lúc import (`app.auth`); test nào đặt lại None thì khôi phục
    sau test, không để rò sang test sau."""
    resolver, notifier = principal_mod._state["resolver"], runner._hooks["notifier"]
    yield
    if notifier is not None:
        runner._hooks["notifier"] = notifier
    if resolver is not None:
        principal_mod._state["resolver"] = resolver


@pytest.fixture
def bw_log():
    """Gắn handler tạm vào logger `bw`; trả hàm đọc các dòng JSON đã ghi."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(CidFilter())
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(LOGGER_NAME)
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    def lines() -> list[dict]:
        return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]

    yield lines
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def asgi_client(app) -> httpx2.AsyncClient:
    """Client gọi thẳng ASGI app; lỗi 500 trả về response thay vì ném ra test."""
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")


@pytest.fixture(scope="session")
def auth_keys(tmp_path_factory) -> tuple[str, str]:
    """Cặp khoá Ed25519 riêng cho test (không dùng .secrets thật)."""
    d = tmp_path_factory.mktemp("keys")
    key = Ed25519PrivateKey.generate()
    priv, pub = d / "jwt_private.pem", d / "jwt_public.pem"
    priv.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    pub.write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    return str(priv), str(pub)


@pytest.fixture(scope="session")
def test_settings(auth_keys) -> Settings:
    """Settings trỏ vào tài nguyên *_test: Postgres / Mongo bizwithagents_test, Redis db 11, vhost test."""
    base = get_settings()
    rabbit = base.RABBITMQ_URL or "amqp://bizwithagents:bizwithagents@127.0.0.1:5672/bizwithagents"
    return base.model_copy(
        update={
            "POSTGRES_RW_URL": base.POSTGRES_RW_URL.rsplit("/", 1)[0] + "/bizwithagents_test",
            "POSTGRES_RO_URL": "",
            "MONGO_ENABLED": True,
            "MONGO_RW_URL": base.MONGO_RW_URL or "mongodb://127.0.0.1:27017",
            "MONGO_RO_URL": "",
            "MONGO_DB_NAME": "bizwithagents_test",
            "REDIS_RW_URL": base.REDIS_RW_URL.rsplit("/", 1)[0] + f"/{TEST_REDIS_DB}",
            "REDIS_RO_URL": "",
            "RABBITMQ_URL": rabbit.rsplit("/", 1)[0] + "/bizwithagents_test",
            "SCHEDULER_LEADER_KEY": "bw:test:leader:schedule",
            "SCHEDULER_LEADER_TTL": 2,
            "HEARTBEAT_INTERVAL": 1.0,
            "AUTH_ALGORITHM": "EdDSA",
            "AUTH_PRIVATE_KEY": "",
            "AUTH_PUBLIC_KEY": "",
            "AUTH_PRIVATE_KEY_FILE": auth_keys[0],
            "AUTH_PUBLIC_KEY_FILE": auth_keys[1],
            "SUPERADMIN_EMAILS": "root@test.local",
            "LOG_JSON": True,
        }
    )


def reset_test_redis(settings: Settings) -> None:
    """FLUSHDB db Redis của test. Từ chối mọi URL khác db test."""
    assert settings.REDIS_RW_URL.endswith(f"/{TEST_REDIS_DB}"), "reset_test_redis chỉ chạy trên db test"
    client = redis.Redis.from_url(settings.REDIS_RW_URL)
    try:
        client.flushdb()
    finally:
        client.close()


def head_revision() -> str:
    """Revision cuối của chuỗi migration — module mới thêm migration không phải sửa test lõi."""
    (head,) = ScriptDirectory.from_config(alembic_config(Settings(_env_file=None))).get_heads()
    return head


def reset_test_db(settings: Settings) -> None:
    """Xoá sạch schema public của DB test. Từ chối mọi DB không kết thúc bằng `_test`."""
    dsn = settings.POSTGRES_RW_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    assert dsn.rsplit("/", 1)[1].endswith("_test"), "reset_test_db chỉ chạy trên DB *_test"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")


async def reset_rabbit(settings: Settings, queues=(), exchanges=()) -> None:
    """Xoá queue / exchange trên vhost test. Từ chối mọi vhost không kết thúc bằng `_test`."""
    assert settings.RABBITMQ_URL.rsplit("/", 1)[1].endswith("_test"), "reset_rabbit chỉ chạy trên vhost *_test"
    conn = await aio_pika.connect(settings.RABBITMQ_URL)
    try:
        ch = await conn.channel()
        for name in queues:
            await ch.queue_delete(name)
        for name in exchanges:
            await ch.exchange_delete(name)
    finally:
        await conn.close()


@pytest.fixture
def memory_sinks():
    """Sink quan sát trong bộ nhớ; xong test đặt lại Noop."""
    events, issues = MemoryEventLog(), MemoryIssues()
    set_sinks(Sinks(event_log=events, issues=issues, enabled=True))
    yield SimpleNamespace(events=events, issues=issues)
    set_sinks(noop_sinks())


async def until(cond, timeout: float = 5.0) -> bool:
    """Chờ tới khi `cond()` đúng (thử mỗi 50 ms); trả kết quả cuối."""
    for _ in range(int(timeout / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return bool(cond())


async def get_one(queue, timeout: float = 5.0):
    """Lấy 1 message từ queue aio-pika (basic.get không chờ → thử lại tới khi có hoặc hết giờ)."""
    for _ in range(int(timeout / 0.05)):
        msg = await queue.get(fail=False)
        if msg is not None:
            await msg.ack()
            return msg
        await asyncio.sleep(0.05)
    raise AssertionError("không nhận được message")


@pytest.fixture
async def messaging_env(test_settings):
    """Redis db test sạch + kết nối role api (Mongo tắt) + MessagingHub trên vhost bizwithagents_test."""
    s = test_settings.model_copy(update={"MONGO_ENABLED": False})
    use_settings(s)
    reset_test_redis(s)
    await init_connections("api", s)
    hub = MessagingHub(s)
    set_hub(hub)
    yield s
    set_hub(None)
    await hub.close()
    await close_connections()
    use_settings(None)


class RecordingHub:
    """Thay MessagingHub ở test không cần RabbitMQ: ghi lại mọi lần publish; `fail=True` → publish ném lỗi."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.fail = False

    async def publish(
        self,
        body,
        *,
        queue="",
        exchange=None,
        routing_key="",
        persist=False,
        message_id=None,
        mandatory=True,
        headers=None,
    ) -> str:
        if self.fail:
            raise ConnectionError("RabbitMQ không tới được")
        cid = get_cid() or new_cid()
        exchange_name = getattr(exchange, "name", None)
        self.sent.append(
            {"body": body, "queue": queue, "exchange": exchange_name, "routing_key": routing_key, "cid": cid}
        )
        return cid

    async def declare_queue(self, queue) -> None:
        return None

    async def declare_exchange(self, exchange) -> None:
        return None

    def events(self) -> list[tuple[str, str, dict]]:
        """(routing key, event, data) của mọi message ra `bw.rt.out`, theo thứ tự gửi."""
        return [
            (m["routing_key"], m["body"]["event"], m["body"]["data"]) for m in self.sent if m["exchange"] == "bw.rt.out"
        ]


@pytest.fixture
def recording_hub():
    hub = RecordingHub()
    set_hub(hub)
    yield hub
    set_hub(None)


def plain_dsn(settings: Settings) -> str:
    return settings.POSTGRES_RW_URL.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
async def op_env(test_settings, recording_hub, memory_sinks):
    """DB test sạch + bảng `fx_notes` + kết nối role api (Mongo tắt) + hub ghi lại + sink trong bộ nhớ."""
    s = test_settings.model_copy(update={"MONGO_ENABLED": False})
    use_settings(s)
    reset_test_db(s)
    reset_test_redis(s)
    with psycopg.connect(plain_dsn(s), autocommit=True) as conn:
        conn.execute(fx_ops.FX_TABLE)
    fx_ops.HOOKS.clear()
    conns = await init_connections("api", s)
    yield SimpleNamespace(
        settings=s, conns=conns, hub=recording_hub, events=memory_sinks.events, issues=memory_sinks.issues
    )
    await close_connections()
    use_settings(None)


def api_routes(app) -> list[SimpleNamespace]:
    """Mọi route API của app, kể cả route gắn qua `include_router` (FastAPI 0.141 không trải phẳng `app.routes`):
    mỗi phần tử có `.name`, `.path` (đã kèm prefix), `.methods`, `.endpoint`."""
    out = []
    for r in app.routes:
        if isinstance(r, APIRoute):
            out.append(SimpleNamespace(name=r.name, path=r.path, methods=r.methods, endpoint=r.endpoint))
        elif hasattr(r, "effective_route_contexts"):
            for ctx in r.effective_route_contexts():
                route = ctx.original_route
                if isinstance(route, APIRoute):
                    endpoint = ctx.endpoint or route.endpoint
                    out.append(
                        SimpleNamespace(name=route.name, path=ctx.path, methods=route.methods, endpoint=endpoint)
                    )
    return out


@pytest.fixture
async def app_env(messaging_env):
    """messaging_env + DB test sạch đã migrate + bước sau migrate (catalog quyền, role có sẵn, superadmin) + mọi miền
    đã nạp + khoá JWT test. Trả Settings ĐANG dùng — đổi giới hạn bằng `monkeypatch.setattr(app_env, …)`."""
    s = messaging_env.model_copy(update={"AUTH_LOGIN_RATE_LIMIT": 1000, "AUTH_REGISTER_RATE_LIMIT": 1000})
    use_settings(s)
    configure_tokens(s)
    reset_test_db(s)
    load_domains()
    run_migrations(s)
    await run_post_migrate(s)
    yield s


@pytest.fixture
async def api(app_env):
    """App thật (create_app, không lifespan) trên app_env; trả `tests.auth.api.Api`."""
    app = create_app(app_env, connect=False)
    app.state.conns = get_connections()
    async with asgi_client(app) as client:
        yield Api(client)


@pytest.fixture
def rt(app_env, recording_hub):
    """Event realtime backend gửi ra: RecordingHub thay hub thật SAU app_env — không cần RabbitMQ."""
    return recording_hub
