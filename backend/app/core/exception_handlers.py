"""Mọi lỗi rời app dưới dạng ApiResponse."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.cid import CID_HEADER, get_cid
from app.core.errors import AppException, error_message
from app.core.logging import get_logger
from app.core.response import ApiResponse
from app.observability.sinks import capture_issue

logger = get_logger(__name__)


def _json(status: int, code: int, message: str, data: object = None) -> JSONResponse:
    # lỗi validate của pydantic có thể mang exception trong `ctx` → ép về chuỗi thay vì nổ 500
    safe = jsonable_encoder(data, custom_encoder={BaseException: str})
    return JSONResponse(status_code=status, content=jsonable_encoder(ApiResponse.fail(code, message, safe)))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _app(_: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "AppException code=%s status=%s: %s", exc.code, exc.status_code, exc.message, extra={"loc": "exc0001"}
        )
        return _json(exc.status_code, exc.code, exc.message, exc.data)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _json(422, 1002, error_message(1002), exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = 1001 if exc.status_code == 404 else 1003
        return _json(exc.status_code, code, str(exc.detail) if exc.detail else error_message(code))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("lỗi không xử lý: %s", exc, extra={"loc": "exc0500"})
        principal = getattr(request.state, "principal", None)
        await capture_issue(
            exc,
            source="http",
            loc="exc0500",
            context={
                "method": request.method,
                "path": request.url.path,
                "user_id": getattr(principal, "user_id", None),
            },
        )
        response = _json(500, 1000, error_message(1000))
        # Starlette render 500 ở ServerErrorMiddleware — ngoài HttpLogMiddleware nên tự gắn cid
        if cid := get_cid():
            response.headers[CID_HEADER] = cid
        return response
