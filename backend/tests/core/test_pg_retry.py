"""retry_on_disconnect: chỉ thử lại lỗi mất kết nối, tối đa N lần, lỗi khác ném ngay."""

import psycopg
import pytest

from app.core.connections.postgres import is_disconnect_error, retry_on_disconnect


class Wrapped(Exception):
    def __init__(self, orig):
        super().__init__("wrapped")
        self.orig = orig


def test_disconnect_detection():
    assert is_disconnect_error(psycopg.OperationalError("gone"))
    assert is_disconnect_error(Wrapped(psycopg.OperationalError("gone")))
    invalidated = Exception("x")
    invalidated.connection_invalidated = True
    assert is_disconnect_error(invalidated)
    assert not is_disconnect_error(ValueError("nope"))


async def test_retries_disconnect_then_succeeds(monkeypatch, bw_log):
    monkeypatch.setattr("app.core.connections.postgres.asyncio.sleep", _no_sleep)
    calls = []

    @retry_on_disconnect(2)
    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise Wrapped(psycopg.OperationalError("server closed"))
        return "ok"

    assert await flaky() == "ok" and len(calls) == 3
    assert [r["loc"] for r in bw_log() if r.get("loc") == "db0004"] == ["db0004", "db0004"]


async def test_gives_up_after_max_and_does_not_retry_other_errors(monkeypatch):
    monkeypatch.setattr("app.core.connections.postgres.asyncio.sleep", _no_sleep)
    calls = []

    @retry_on_disconnect(1)
    async def always_down():
        calls.append(1)
        raise psycopg.OperationalError("down")

    with pytest.raises(psycopg.OperationalError):
        await always_down()
    assert len(calls) == 2

    @retry_on_disconnect(3)
    async def bug():
        calls.append(2)
        raise ValueError("logic")

    with pytest.raises(ValueError):
        await bug()
    assert calls.count(2) == 1


async def _no_sleep(_seconds):
    return None
