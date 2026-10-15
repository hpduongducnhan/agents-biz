import pytest
from fastapi import FastAPI

from app.core import errors
from app.core.errors import AppException, error_message, register_errors, registered_errors
from app.core.exception_handlers import register_exception_handlers
from app.core.response import ApiResponse
from tests.conftest import asgi_client


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/conflict")
    async def conflict():
        raise AppException(1006, status_code=409, detail="trùng tên")

    @app.get("/boom")
    async def boom():
        raise RuntimeError("nổ")

    @app.get("/v")
    async def v(n: int):
        return ApiResponse.ok({"n": n})

    return app


async def test_app_exception_renders_envelope():
    async with asgi_client(build_app()) as c:
        r = await c.get("/conflict")
    assert r.status_code == 409
    body = r.json()
    assert body["success"] is False and body["code"] == 1006 and body["message"] == "trùng tên"


async def test_ok_envelope():
    async with asgi_client(build_app()) as c:
        r = await c.get("/v", params={"n": 3})
    assert r.json() == {"success": True, "code": 0, "message": "OK", "data": {"n": 3}, "correlation_id": None}


async def test_validation_error_is_1002():
    async with asgi_client(build_app()) as c:
        r = await c.get("/v", params={"n": "abc"})
    assert r.status_code == 422
    assert r.json()["code"] == 1002 and isinstance(r.json()["data"], list)


async def test_unknown_route_is_1001():
    async with asgi_client(build_app()) as c:
        r = await c.get("/nope")
    assert r.status_code == 404 and r.json()["code"] == 1001


async def test_unhandled_exception_is_1000_and_logged(bw_log):
    async with asgi_client(build_app()) as c:
        r = await c.get("/boom")
    assert r.status_code == 500 and r.json()["code"] == 1000
    assert any(line["loc"] == "exc0500" and "RuntimeError" in line.get("exc", "") for line in bw_log())


@pytest.fixture
def isolated_registry(monkeypatch):
    monkeypatch.setattr(errors, "_REGISTRY", dict(errors._REGISTRY))


def test_register_errors_checks_owner_and_range(isolated_registry):
    with pytest.raises(ValueError, match="owner"):
        register_errors({2001: "x"}, owner="test")
    with pytest.raises(ValueError, match="ngoài dải"):
        register_errors({1500: "x"}, owner="auth")
    register_errors({2999: "Lỗi thử"}, owner="auth")
    assert error_message(2999) == "Lỗi thử" and registered_errors()[2999] == ("Lỗi thử", "auth")
    assert error_message(59999) == "Error 59999"


def test_shared_range_still_rejects_cross_owner_duplicates(isolated_registry):
    register_errors({7999: "a"}, owner="observability")
    register_errors({7999: "a"}, owner="observability")  # nạp lại cùng owner — không lỗi
    with pytest.raises(ValueError, match="trùng"):
        register_errors({7999: "b"}, owner="notifications")


def test_core_codes_sit_in_core_range():
    assert all(1000 <= code <= 1999 for code, (_, owner) in registered_errors().items() if owner == "core")
