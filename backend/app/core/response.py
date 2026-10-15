"""Envelope thống nhất cho mọi response HTTP: `{success, code, message, data, correlation_id}`."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from app.core.cid import get_cid

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    code: int = 0
    message: str = "OK"
    data: T | None = None
    correlation_id: str | None = None

    @classmethod
    def ok(cls, data: T | None = None, message: str = "OK") -> ApiResponse[T]:
        return cls(success=True, code=0, message=message, data=data, correlation_id=get_cid())

    @classmethod
    def fail(cls, code: int, message: str, data: object = None) -> ApiResponse:
        return cls(success=False, code=code, message=message, data=data, correlation_id=get_cid())
