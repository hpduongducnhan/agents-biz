"""Sinh route REST từ @operation: đường dẫn suy từ tên — GET + query cho effect read, POST + body
JSON cho còn lại; mọi lỗi dữ liệu → 422 mã 1002, không 500."""

from __future__ import annotations

import functools
import json
import types
import typing
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from app.core.errors import AppException
from app.core.operations.registry import specs_for
from app.core.operations.runner import run_operation
from app.core.operations.spec import OperationSpec
from app.core.response import ApiResponse
from app.core.security.principal import Principal, resolve_principal

_QUERY_METHODS = ("GET", "DELETE")


def _invalid_body(msg: str, kind: str) -> AppException:
    return AppException(1002, status_code=422, data=[{"type": kind, "loc": ["body"], "msg": msg}])


async def json_object(request: Request) -> dict:
    """Body JSON phải là object; rỗng = {}. Sai → 422 mã 1002."""
    raw = await request.body()
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise _invalid_body("JSON không hợp lệ", "json_invalid") from exc
    if not isinstance(body, dict):
        raise _invalid_body("body phải là object JSON", "dict_type")
    return body


async def request_data(request: Request, method: str, spec: OperationSpec) -> dict | None:
    if spec.input_model is None:
        return None
    if method in _QUERY_METHODS:
        lists = list_fields(spec.input_model)
        data: dict = {}
        for key in request.query_params:
            values = request.query_params.getlist(key)
            data[key] = values if key in lists or len(values) > 1 else values[0]
        return data
    return await json_object(request)


@functools.cache
def list_fields(model: type[BaseModel]) -> frozenset[str]:
    """Trường kiểu danh sách của input (kể cả `list[...] | None`) — query string một giá trị vẫn phải thành list."""

    def is_list(tp: Any) -> bool:
        origin = typing.get_origin(tp)
        if origin in (list, tuple, set, frozenset):
            return True
        return origin in (typing.Union, types.UnionType) and any(is_list(a) for a in typing.get_args(tp))

    return frozenset(name for name, field in model.model_fields.items() if is_list(field.annotation))


async def _principal(spec: OperationSpec, request: Request) -> Principal | None:
    if not spec.public:
        return await resolve_principal(request)  # None → runner trả 1004
    try:
        return await resolve_principal(request)
    except AppException:
        return None  # operation công khai: token hỏng / hết hạn → ẩn danh (vd refresh khi access đã hết hạn)


def _inline_defs(schema: dict) -> dict:
    """Thay `{"$ref": "#/$defs/X"}` bằng bản sao của X rồi bỏ `$defs` — input lồng model (vd `policies`) nằm thẳng
    trong requestBody / parameters; `$ref` cục bộ kiểu `#/$defs/…` không trỏ được trong tài liệu OpenAPI."""
    defs = schema.get("$defs", {})

    def walk(node: Any, depth: int = 0) -> Any:
        if depth > 32:
            raise ValueError("schema input lồng quá sâu / đệ quy — không inline được")
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = walk(defs[ref.removeprefix("#/$defs/")], depth + 1)
                extra = {k: walk(v, depth + 1) for k, v in node.items() if k != "$ref"}
                return {**target, **extra}
            out = {k: walk(v, depth + 1) for k, v in node.items() if k != "$defs"}
            if isinstance(out.get("discriminator"), dict):  # mapping trỏ `#/$defs/…` — các nhánh đã inline ngay tại chỗ
                out["discriminator"] = {k: v for k, v in out["discriminator"].items() if k != "mapping"}
            return out
        if isinstance(node, list):
            return [walk(v, depth + 1) for v in node]
        return node

    return walk(schema)


def _openapi_extra(spec: OperationSpec, method: str) -> dict | None:
    if spec.input_model is None:
        return None
    schema = _inline_defs(spec.input_model.model_json_schema())
    if method in _QUERY_METHODS:
        required = set(schema.get("required", []))
        params = [
            {"name": n, "in": "query", "required": n in required, "schema": p}
            for n, p in schema.get("properties", {}).items()
        ]
        return {"parameters": params}
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": schema}}}}


def _responses(spec: OperationSpec) -> dict:
    """Response trong OpenAPI = envelope bọc kiểu trả về của handler (R6, R7) — frontend sinh type output từ đây.
    Handler không khai kiểu trả về → `ApiResponse[Any]`."""
    output = spec.output_model if spec.output_model is not None else Any
    return {spec.status_code: {"model": ApiResponse[output], "description": "OK"}}


def _endpoint(spec: OperationSpec, method: str):
    async def endpoint(request: Request):
        principal = await _principal(spec, request)
        data = await request_data(request, method, spec)
        ip = request.client.host if request.client else None
        result = await run_operation(spec.name, principal, data, source="web", request_ip=ip)
        return ApiResponse.ok(jsonable_encoder(result))

    endpoint.__name__ = spec.name.replace(".", "_")
    endpoint.__bw_operation__ = spec
    return endpoint


def build_operation_router(namespace: str) -> APIRouter:
    """Router REST của một namespace operation — gắn dưới `api_prefix`."""
    router = APIRouter(tags=[namespace])
    seen: dict[tuple[str, str], str] = {}
    for spec in specs_for(namespace):
        method, path = spec.route
        if (method, path) in seen:
            raise ValueError(f"route {method} {path} bị trùng giữa {seen[(method, path)]} và {spec.name}")
        seen[(method, path)] = spec.name
        router.add_api_route(
            path,
            _endpoint(spec, method),
            methods=[method],
            name=spec.name,
            summary=spec.title,
            description=spec.description,
            operation_id=spec.name,
            status_code=spec.status_code,
            response_model=None,
            responses=_responses(spec),
            openapi_extra=_openapi_extra(spec, method),
        )
    return router
