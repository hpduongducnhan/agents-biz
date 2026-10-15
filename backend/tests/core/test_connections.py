"""Kết nối 2 kênh RW / RO: RO chỉ đọc, after-commit chỉ chạy khi commit, pool thô do lõi giữ, Beanie theo kênh RW."""

import psycopg
import pytest
from beanie import Document
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.connections.documents import init_documents
from app.core.connections.mongo import Mongo
from app.core.connections.postgres import Postgres, after_commit
from app.core.connections.redis import Redis
from app.core.connections.registry import close_connections, get_connections, init_connections

pytestmark = pytest.mark.integration


class Probe(Document):
    v: int

    class Settings:
        name = "_test_bw_probe"


@pytest.fixture
async def pg(test_settings):
    p = Postgres(test_settings)
    yield p
    await p.close()


@pytest.fixture
async def mongo(test_settings):
    m = Mongo(test_settings)
    yield m
    for name in ("_test_bw_conn", "_test_bw_conn_out", "_test_bw_probe"):
        await m.rw[name].drop()
    await m.close()


@pytest.fixture
async def rds(test_settings):
    r = Redis(test_settings)
    yield r
    await r.rw.delete("bw:test:conn")
    await r.close()


async def test_ro_channels_fall_back_to_rw_but_have_own_pools(test_settings, pg):
    assert test_settings.postgres_ro_url == test_settings.POSTGRES_RW_URL
    assert pg.ro_engine is not pg.rw_engine


async def test_postgres_ro_session_is_read_only(pg):
    with pytest.raises(DBAPIError) as err:
        async with pg.ro() as s:
            await s.exec(text("CREATE TEMP TABLE bw_probe (x int)"))
    assert isinstance(err.value.orig, psycopg.errors.ReadOnlySqlTransaction)


async def test_postgres_rw_read_only_transaction(pg):
    with pytest.raises(DBAPIError) as err:
        async with pg.rw(read_only=True) as s:
            await s.exec(text("CREATE TEMP TABLE bw_probe (x int)"))
    assert isinstance(err.value.orig, psycopg.errors.ReadOnlySqlTransaction)


async def test_after_commit_hooks_run_only_after_commit(pg, bw_log):
    calls: list[str] = []

    async def hook():
        calls.append("ran")

    async def broken():
        raise ConnectionError("hook hỏng")

    async with pg.rw() as s:
        await s.exec(text("SELECT 1"))
        after_commit(s, hook)
        after_commit(s, broken)
        assert calls == []
    assert calls == ["ran"]
    assert any(line["loc"] == "db0003" and "hook hỏng" in line["msg"] for line in bw_log())

    with pytest.raises(RuntimeError):
        async with pg.rw() as s:
            after_commit(s, hook)
            raise RuntimeError("rollback")
    assert calls == ["ran"]


async def test_failed_rollback_does_not_hide_original_exception(pg, monkeypatch, bw_log):
    make_session = pg._rw_sessions

    def session_with_broken_rollback():
        session = make_session()

        async def broken_rollback():
            raise ConnectionError("rollback hỏng")

        session.rollback = broken_rollback
        return session

    monkeypatch.setattr(pg, "_rw_sessions", session_with_broken_rollback)
    with pytest.raises(ValueError, match="lỗi gốc"):
        async with pg.rw():
            raise ValueError("lỗi gốc")
    logged = [line for line in bw_log() if line.get("loc") == "db0005"]
    assert logged and "rollback hỏng" in logged[0]["msg"]


async def test_raw_pool_is_owned_by_the_core_and_keyed(pg):
    pool = await pg.raw_pool("lg", search_path="pg_catalog", dict_rows=True)
    assert await pg.raw_pool("lg", search_path="pg_catalog", dict_rows=True) is pool
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT current_schema() AS s")).fetchone()
        assert row == {"s": "pg_catalog"} and conn.autocommit
    other = await pg.raw_pool("plain")
    assert other is not pool
    await pg.close()
    assert pool.closed and other.closed


async def test_mongo_rw_write_ro_read(mongo):
    await mongo.rw["_test_bw_conn"].insert_one({"_id": "k1", "v": 1})
    assert (await mongo.ro["_test_bw_conn"].find_one({"_id": "k1"}))["v"] == 1
    assert (await mongo.rw_read_only.get_collection("_test_bw_conn").find_one({"_id": "k1"}))["v"] == 1
    assert mongo.ro.name == "bizwithagents_test" and mongo.ro["_test_bw_conn"].name == "_test_bw_conn"
    assert "_test_bw_conn" in await mongo.ro.list_collection_names()


async def test_mongo_ro_blocks_writes(mongo):
    with pytest.raises(AttributeError, match="RW"):
        mongo.ro["_test_bw_conn"].insert_one({"x": 1})


async def test_mongo_ro_aggregate_cannot_write(mongo):
    await mongo.rw["_test_bw_conn"].insert_one({"_id": "k1", "v": 1})
    for stage in ({"$out": "_test_bw_conn_out"}, {"$merge": {"into": "_test_bw_conn_out"}}):
        with pytest.raises(PermissionError, match="RW"):
            await mongo.ro["_test_bw_conn"].aggregate([{"$match": {}}, stage])
    assert "_test_bw_conn_out" not in await mongo.rw.list_collection_names()
    cursor = await mongo.ro["_test_bw_conn"].aggregate([{"$match": {"_id": "k1"}}])
    assert [d["v"] async for d in cursor] == [1]


async def test_beanie_documents_bind_to_rw_database(mongo, bw_log):
    await init_documents(mongo, [])
    assert not any(line["loc"] == "db0010" for line in bw_log())
    await init_documents(mongo, [Probe])
    await Probe(v=7).insert()
    assert (await Probe.find_one(Probe.v == 7)).v == 7
    assert any(line["loc"] == "db0010" for line in bw_log())


async def test_redis_rw_write_ro_read(rds):
    await rds.rw.set("bw:test:conn", "v1", ex=30)
    assert await rds.ro.get("bw:test:conn") == "v1"


async def test_redis_ro_blocks_writes(rds):
    with pytest.raises(AttributeError, match="RW"):
        rds.ro.set("bw:test:conn", "x")


async def test_init_connections_by_role(test_settings, bw_log):
    conns = await init_connections("migrate", test_settings)
    try:
        assert conns.postgres is not None and conns.mongo is None and conns.redis is None
        assert get_connections() is conns
        assert await conns.health() == {"postgres.rw": "ok", "postgres.ro": "ok"}
    finally:
        await close_connections()
    assert any(line["loc"] == "db0001" for line in bw_log())
    with pytest.raises(RuntimeError):
        get_connections()
