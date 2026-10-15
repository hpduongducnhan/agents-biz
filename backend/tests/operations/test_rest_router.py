"""build_operation_router: đường dẫn suy từ tên (GET cho đọc, POST cho ghi), route trùng bị từ chối, endpoint mang
dấu operation, OpenAPI mô tả query / body."""

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.core.operations import registry
from app.core.operations.pagination import PageIn
from app.core.operations.rest import build_operation_router
from app.core.operations.spec import operation


class FindIn(PageIn):
    q: str = ""


class SaveIn(BaseModel):
    title: str


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(registry, "_SPECS", {})


def declare():
    @operation("rtdemo.find_items", title="Tìm")
    async def find_items(ctx, inp: FindIn) -> list:
        return []

    @operation("rtdemo.save_item", title="Lưu", effect="write")
    async def save_item(ctx, inp: SaveIn) -> dict:
        return {}

    @operation("rtdemo.drop_item", title="Xoá", effect="destructive")
    async def drop_item(ctx) -> dict:
        return {}


def routes(router) -> dict[str, APIRoute]:
    return {r.name: r for r in router.routes if isinstance(r, APIRoute)}


def test_paths_follow_name_and_effect():
    declare()
    got = {name: (r.methods, r.path) for name, r in routes(build_operation_router("rtdemo")).items()}
    assert got == {
        "rtdemo.find_items": ({"GET"}, "/rtdemo/find_items"),
        "rtdemo.save_item": ({"POST"}, "/rtdemo/save_item"),
        "rtdemo.drop_item": ({"POST"}, "/rtdemo/drop_item"),
    }


def test_endpoint_carries_operation_marker_and_openapi_shape():
    declare()
    by_name = routes(build_operation_router("rtdemo"))
    find, save = by_name["rtdemo.find_items"], by_name["rtdemo.save_item"]
    assert find.endpoint.__bw_operation__.name == "rtdemo.find_items"
    params = {p["name"]: p for p in find.openapi_extra["parameters"]}
    assert set(params) == {"limit", "offset", "q"} and all(p["in"] == "query" for p in params.values())
    body = save.openapi_extra["requestBody"]["content"]["application/json"]["schema"]
    assert body["required"] == ["title"]
    assert by_name["rtdemo.drop_item"].openapi_extra is None


def test_openapi_response_is_envelope_of_handler_output():
    """R7: frontend sinh type output từ OpenAPI → response phải khai envelope bọc đúng kiểu trả về của handler."""
    declare()
    app = FastAPI()
    app.include_router(build_operation_router("rtdemo"))
    doc = app.openapi()
    for path, method in (("/rtdemo/find_items", "get"), ("/rtdemo/save_item", "post"), ("/rtdemo/drop_item", "post")):
        schema = doc["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        envelope = doc["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
        assert set(envelope["properties"]) == {"success", "code", "message", "data", "correlation_id"}, path
    data = doc["components"]["schemas"]["ApiResponse_list_"]["properties"]["data"]
    assert any(item.get("type") == "array" for item in data.get("anyOf", [data]))


def test_duplicate_route_is_rejected():
    @operation("dupdemo.list_items", title="A")
    async def list_items(ctx) -> list:
        return []

    @operation("dupdemo.other", title="B", http=("GET", "/dupdemo/list_items"))
    async def other(ctx) -> list:
        return []

    with pytest.raises(ValueError, match="trùng"):
        build_operation_router("dupdemo")
