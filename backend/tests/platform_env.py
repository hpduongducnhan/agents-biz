"""Môi trường test tích hợp: DB test sạch đã migrate (+ bước sau migrate), kết nối theo cờ Mongo, messaging,
app thật cho REST (helper `Api`). Fixture `stack` chạy mỗi test ở CẢ HAI chế độ Mongo."""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import aio_pika
import pytest
from pymongo import AsyncMongoClient

from app.auth.ops.auth import jwt_resolver
from app.auth.tokens import configure_tokens
from app.core.connections.registry import Connections, close_connections, init_connections
from app.core.messaging import names
from app.core.messaging.runtime import start_messaging, stop_messaging
from app.core.migrate import run_migrations, run_post_migrate
from app.core.security.principal import Principal, set_principal_resolver
from app.core.settings import Settings, use_settings
from app.domains import load_domains
from app.main import create_app
from app.observability import close_observability, init_observability
from tests.auth.api import Api, Session
from tests.conftest import asgi_client, reset_test_db, reset_test_redis

MONGO_COLLECTIONS = ("event_log", "issues")
SUPERADMIN_EMAIL = "root@test.local"  # có trong SUPERADMIN_EMAILS của test_settings


@dataclass
class Stack:
    settings: Settings
    conns: Connections
    api: Api


async def drop_test_mongo(settings: Settings) -> None:
    """Xoá collection quan sát của DB Mongo test. Từ chối mọi DB không kết thúc bằng `_test`."""
    assert settings.MONGO_DB_NAME.endswith("_test"), "drop_test_mongo chỉ chạy trên DB *_test"
    client = AsyncMongoClient(settings.MONGO_RW_URL)
    try:
        for name in MONGO_COLLECTIONS:
            await client[settings.MONGO_DB_NAME].drop_collection(name)
    finally:
        await client.close()


@asynccontextmanager
async def platform_env(base: Settings, *, mongo: bool, **overrides: Any) -> AsyncIterator[Stack]:
    limits = {"AUTH_LOGIN_RATE_LIMIT": 1000, "AUTH_REGISTER_RATE_LIMIT": 1000}
    no_google = {
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
        "GOOGLE_REDIRECT_URI": "",
    }  # không phụ thuộc env máy
    s = base.model_copy(update={"MONGO_ENABLED": mongo, **limits, **no_google, **overrides})
    use_settings(s)
    set_principal_resolver(
        jwt_resolver
    )  # test operations/ đặt resolver giả rồi xoá về None → cài lại resolver JWT thật
    configure_tokens(s)
    reset_test_db(s)
    reset_test_redis(s)
    if mongo:
        await drop_test_mongo(s)
    load_domains()
    run_migrations(s)
    await run_post_migrate(s)
    conns = await init_connections("api", s)
    await init_observability(s, conns.mongo)
    await start_messaging(s, "test")
    app = create_app(s, connect=False)
    app.state.conns = conns
    try:
        async with asgi_client(app) as client:
            yield Stack(settings=s, conns=conns, api=Api(client))
    finally:
        await stop_messaging()
        await close_observability()
        await close_connections()
        use_settings(None)


@pytest.fixture(params=[pytest.param(True, id="mongo-on"), pytest.param(False, id="mongo-off")])
async def stack(request, test_settings) -> AsyncIterator[Stack]:
    async with platform_env(test_settings, mongo=request.param) as env:
        yield env


@pytest.fixture
async def mongo_stack(test_settings) -> AsyncIterator[Stack]:
    async with platform_env(test_settings, mongo=True) as env:
        yield env


@pytest.fixture
async def plain_stack(test_settings) -> AsyncIterator[Stack]:
    async with platform_env(test_settings, mongo=False) as env:
        yield env


def as_principal(who: Session, *, sup: bool = False) -> Principal:
    """Principal của một phiên đăng nhập — để gọi `run_operation` / handler socket trực tiếp."""
    return Principal(user_id=uuid.UUID(who.id), perms=frozenset(), sup=sup)


async def superadmin(stack: Stack) -> Session:
    return await stack.api.as_user(SUPERADMIN_EMAIL)


async def eventually(check: Callable[[], Any], *, timeout: float = 5.0, interval: float = 0.05) -> Any:
    """Chờ `check()` (sync hoặc async) trả giá trị truthy — ghi nền / realtime là bất đồng bộ. Hết giờ → lỗi."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        value = check()
        if inspect.isawaitable(value):
            value = await value
        if value:
            return value
        if loop.time() > deadline:
            raise AssertionError("hết giờ chờ điều kiện")
        await asyncio.sleep(interval)


class RtTap:
    """Queue tạm bind `bw.rt.out` theo routing key — đọc đúng envelope backend gửi cho service realtime."""

    def __init__(self, queue: aio_pika.abc.AbstractQueue) -> None:
        self.queue = queue
        self.seen: list[tuple[str, dict]] = []

    async def bind(self, *keys: str) -> None:
        for key in keys:
            await self.queue.bind(names.RT_OUT_EXCHANGE, routing_key=key)

    async def data(self, key: str, event: str, wait: float = 0.3) -> list[dict]:
        """`data` của mọi envelope `event` đã tới routing key `key` (chờ `wait` giây cho message trên đường)."""
        await asyncio.sleep(wait)
        while (msg := await self.queue.get(fail=False)) is not None:
            await msg.ack()
            self.seen.append((msg.routing_key, json.loads(msg.body)))
        return [body["data"] for routing_key, body in self.seen if routing_key == key and body["event"] == event]


@asynccontextmanager
async def rt_listener(stack: Stack) -> AsyncIterator[RtTap]:
    """`RtTap` trên queue tạm của vhost test — `bind("user.<id>")` / `bind("sup")` rồi `data(key, event)`."""
    conn = await aio_pika.connect(stack.settings.RABBITMQ_URL)
    try:
        channel = await conn.channel()
        await channel.declare_exchange(names.RT_OUT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        yield RtTap(await channel.declare_queue(exclusive=True))
    finally:
        await conn.close()
