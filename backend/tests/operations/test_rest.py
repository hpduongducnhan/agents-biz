"""REST trên app `api` thật: GET + query cho đọc, POST + body cho ghi; input sai luôn 4xx có mã; operation công khai
với token hỏng chạy như ẩn danh; log HTTP mang user + miền; app thật không gắn miền giả."""

import uuid

import pytest

from app.core.errors import AppException
from app.core.operations.rest import build_operation_router
from app.core.security.principal import Principal, set_principal_resolver
from app.main import create_app
from tests.conftest import api_routes, asgi_client

pytestmark = pytest.mark.integration
PREFIX = "/bizwithagents/api"
U1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
WRITER = Principal(user_id=U1, perms=frozenset({"fx.write"}))
READER = Principal(user_id=uuid.UUID("00000000-0000-4000-8000-000000000002"))


@pytest.fixture
def current():
    return {"p": WRITER}


@pytest.fixture
def app(op_env, current):
    async def resolver(request):
        if isinstance(current["p"], Exception):
            raise current["p"]
        return current["p"]

    set_principal_resolver(resolver)
    app = create_app(op_env.settings, connect=False)
    app.include_router(build_operation_router("fx"), prefix=PREFIX)  # create_app chỉ gắn operation của app.* (Q5)
    yield app
    set_principal_resolver(None)


def _route(app, name):
    return next(r for r in api_routes(app) if r.name == name)


async def test_derived_routes_for_read_write_destructive(app):
    listing = _route(app, "fx.list_notes")
    assert (listing.methods, listing.path) == ({"GET"}, f"{PREFIX}/fx/list_notes")
    for name in ("fx.create_note", "fx.delete_note", "fx.purge"):
        r = _route(app, name)
        assert r.methods == {"POST"} and r.path == f"{PREFIX}/{name.replace('.', '/')}"


async def test_post_body_then_get_query_roundtrip(app):
    async with asgi_client(app) as c:
        created = await c.post(f"{PREFIX}/fx/create_note", json={"title": "qua REST"})
        listed = await c.get(f"{PREFIX}/fx/list_notes", params={"q": "REST"})
    assert created.status_code == 201 and created.json()["data"]["title"] == "qua REST"
    page = listed.json()["data"]
    assert listed.status_code == 200
    assert page == {"items": [created.json()["data"]], "total": 1, "limit": 20, "offset": 0}


async def test_get_query_params_are_validated_into_input_model(app):
    async with asgi_client(app) as c:
        for title in ("một", "hai", "ba"):
            await c.post(f"{PREFIX}/fx/create_note", json={"title": title})
        ok = await c.get(f"{PREFIX}/fx/list_notes", params={"limit": "2"})
        bad_type = await c.get(f"{PREFIX}/fx/list_notes", params={"limit": "abc"})
        over_max = await c.get(f"{PREFIX}/fx/list_notes", params={"limit": "101"})
        repeated = await c.get(f"{PREFIX}/fx/list_notes?q=a&q=b")
    assert ok.status_code == 200 and [n["title"] for n in ok.json()["data"]["items"]] == ["một", "hai"]
    for r in (bad_type, over_max, repeated):
        assert r.status_code == 422 and r.json()["code"] == 1002, r.text
    assert bad_type.json()["data"][0]["loc"] == ["limit"]


async def test_bad_json_non_object_and_missing_field_are_1002(app):
    async with asgi_client(app) as c:
        bad_json = await c.post(
            f"{PREFIX}/fx/create_note", content=b"{khong phai json", headers={"content-type": "application/json"}
        )
        not_object = await c.post(f"{PREFIX}/fx/create_note", json=[1, 2])
        missing = await c.post(f"{PREFIX}/fx/create_note", json={})
        empty = await c.post(f"{PREFIX}/fx/create_note")
    for r in (bad_json, not_object, missing, empty):
        assert r.status_code == 422 and r.json()["code"] == 1002, r.text


async def test_wrong_method_is_not_500(app):
    async with asgi_client(app) as c:
        r = await c.get(f"{PREFIX}/fx/create_note")
    assert r.status_code == 405 and r.json()["code"] == 1003


async def test_no_principal_is_401(app, current):
    current["p"] = None
    async with asgi_client(app) as c:
        r = await c.get(f"{PREFIX}/fx/list_notes")
    assert r.status_code == 401 and r.json()["code"] == 1004


async def test_permission_denied_is_403(app, current):
    current["p"] = READER
    async with asgi_client(app) as c:
        r = await c.post(f"{PREFIX}/fx/create_note", json={"title": "x"})
    assert r.status_code == 403 and r.json()["code"] == 1005


async def test_public_operation_with_broken_token_runs_anonymously(app, current):
    current["p"] = AppException(2104, status_code=401)
    async with asgi_client(app) as c:
        public = await c.get(f"{PREFIX}/fx/ping")
        private = await c.get(f"{PREFIX}/fx/list_notes")
    assert public.status_code == 200 and public.json()["data"] == {"pong": True, "user": None}
    assert private.status_code == 401 and private.json()["code"] == 2104


async def test_public_operation_sees_valid_principal(app):
    async with asgi_client(app) as c:
        r = await c.get(f"{PREFIX}/fx/ping")
    assert r.json()["data"] == {"pong": True, "user": str(U1)}


async def test_http_log_carries_user_and_domain(app, bw_log):
    async with asgi_client(app) as c:
        await c.post(f"{PREFIX}/fx/create_note", json={"title": "log"})
    line = next(line for line in bw_log() if line["loc"] == "http0001")
    assert line["http"]["user"] == str(U1) and line["module"] == "fx"
    assert line["http"]["route"] == f"{PREFIX}/fx/create_note"


async def test_openapi_describes_query_and_body(app):
    async with asgi_client(app) as c:
        spec = (await c.get(f"{PREFIX}/openapi.json")).json()
    listing = spec["paths"][f"{PREFIX}/fx/list_notes"]["get"]
    assert {p["name"] for p in listing["parameters"]} == {"q", "limit", "offset"}
    create = spec["paths"][f"{PREFIX}/fx/create_note"]["post"]
    assert "title" in create["requestBody"]["content"]["application/json"]["schema"]["properties"]


async def test_production_app_does_not_mount_test_domains(op_env):
    app = create_app(op_env.settings, connect=False)
    assert not [r for r in api_routes(app) if r.path.startswith(f"{PREFIX}/fx/")]
