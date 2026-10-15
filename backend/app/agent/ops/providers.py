"""studio.* — provider + model (giá / context window) + thử kết nối provider."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.agent.config import registry, remote_models
from app.agent.config.models import AgentModel, AgentProvider
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.operations.context import OpContext
from app.core.operations.spec import operation
from app.credentials.service import reveal

logger = get_logger(__name__)
REASON = "cấu hình agent — chỉ trên giao diện"
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Kind = Literal["openai", "anthropic", "google_genai", "openai_compatible"]


class ProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    base_url: str | None
    extra_headers: dict
    default_params: dict
    status: str
    models_count: int


class SaveProviderIn(BaseModel):
    provider_id: uuid.UUID | None = None
    name: Name
    kind: Kind
    base_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")
    extra_headers: dict[str, str] = Field(default_factory=dict)
    default_params: dict = Field(default_factory=dict)
    status: Literal["active", "disabled"] = "active"


class ModelOut(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    provider_name: str
    model_id: str
    name: str
    input_price_per_1m: Decimal
    output_price_per_1m: Decimal
    cache_read_price_per_1m: Decimal
    cache_write_price_per_1m: Decimal
    context_window: int | None
    status: str


class SaveModelIn(BaseModel):
    model_ref: uuid.UUID | None = Field(default=None, description="id model cần sửa; trống = tạo mới")
    provider_id: uuid.UUID
    model_id: str = Field(min_length=1, max_length=200)
    name: Name
    input_price_per_1m: Decimal = Field(default=Decimal(0), ge=0)
    output_price_per_1m: Decimal = Field(default=Decimal(0), ge=0)
    cache_read_price_per_1m: Decimal = Field(default=Decimal(0), ge=0)
    cache_write_price_per_1m: Decimal = Field(default=Decimal(0), ge=0)
    context_window: int | None = Field(default=None, ge=1)
    status: Literal["active", "disabled"] = "active"


class IdIn(BaseModel):
    id: uuid.UUID


class TestProviderIn(BaseModel):
    provider_id: uuid.UUID
    credential_id: uuid.UUID


class TestProviderOut(BaseModel):
    ok: bool
    latency_ms: int
    models: list[str] = Field(default_factory=list)
    error: str | None = None


def _studio(name: str, title: str, description: str, effect: str = "write", keys: tuple[str, ...] = ()):
    return operation(
        name,
        title=title,
        description=description,
        effect=effect,
        superadmin=True,
        agent_reason=REASON,
        invalidates=keys,
    )


async def _flush(ctx: OpContext, what: str) -> None:
    try:
        async with ctx.session.begin_nested():
            await ctx.session.flush()
    except IntegrityError as exc:
        raise AppException(1006, status_code=409, detail=f"{what} already exists or is in use") from exc
    await registry.bump(ctx.redis)


async def _models_out(session, rows: list[AgentModel]) -> list[ModelOut]:
    names = {p.id: p.name for p in (await session.exec(select(AgentProvider))).all()}
    return [ModelOut(**m.model_dump(), provider_name=names.get(m.provider_id, "")) for m in rows]


@operation("studio.list_providers", title="Provider", description="Provider LLM đã khai", superadmin=True)
async def list_providers(ctx: OpContext) -> list[ProviderOut]:
    counts = dict(
        (await ctx.session.exec(select(AgentModel.provider_id, func.count()).group_by(AgentModel.provider_id))).all()
    )
    rows = (await ctx.session.exec(select(AgentProvider).order_by(AgentProvider.name))).all()
    return [ProviderOut(**p.model_dump(), models_count=counts.get(p.id, 0)) for p in rows]


@_studio("studio.save_provider", "Lưu provider", "Tạo / sửa provider (loại, địa chỉ, header, tham số mặc định)",
         keys=("studio.providers",))  # fmt: skip
async def save_provider(ctx: OpContext, inp: SaveProviderIn) -> ProviderOut:
    p = (
        await ctx.session.get(AgentProvider, inp.provider_id)
        if inp.provider_id
        else AgentProvider(name=inp.name, kind=inp.kind)
    )
    if p is None:
        raise AppException(1001, status_code=404, detail="Provider not found")
    for k in ("name", "kind", "base_url", "extra_headers", "default_params", "status"):
        setattr(p, k, getattr(inp, k))
    ctx.session.add(p)
    await _flush(ctx, "Provider")
    return ProviderOut(**p.model_dump(), models_count=0)


@_studio("studio.delete_provider", "Xoá provider", "Xoá provider (model của nó bị xoá theo)", "destructive",
         ("studio.providers", "studio.models"))  # fmt: skip
async def delete_provider(ctx: OpContext, inp: IdIn) -> None:
    p = await ctx.session.get(AgentProvider, inp.id)
    if p is None:
        raise AppException(1001, status_code=404, detail="Provider not found")
    await ctx.session.delete(p)
    await _flush(ctx, "Provider")


@operation("studio.list_models", title="Model", description="Model đã khai kèm giá", superadmin=True)
async def list_models(ctx: OpContext) -> list[ModelOut]:
    rows = list((await ctx.session.exec(select(AgentModel).order_by(AgentModel.name))).all())
    return await _models_out(ctx.session, rows)


@_studio(
    "studio.save_model", "Lưu model", "Tạo / sửa model (tên phía provider, giá mỗi 1M token)", keys=("studio.models",)
)
async def save_model(ctx: OpContext, inp: SaveModelIn) -> ModelOut:
    if await ctx.session.get(AgentProvider, inp.provider_id) is None:
        raise AppException(1001, status_code=404, detail="Provider not found")
    m = await ctx.session.get(AgentModel, inp.model_ref) if inp.model_ref else AgentModel(
        provider_id=inp.provider_id, model_id=inp.model_id, name=inp.name
    )  # fmt: skip
    if m is None:
        raise AppException(1001, status_code=404, detail="Model not found")
    for k, v in inp.model_dump(exclude={"model_ref"}).items():
        setattr(m, k, v)
    ctx.session.add(m)
    await _flush(ctx, "Model")
    return (await _models_out(ctx.session, [m]))[0]


@_studio("studio.delete_model", "Xoá model", "Xoá model (agent đang dùng sẽ thành chưa có model)", "destructive",
         ("studio.models", "studio.agents"))  # fmt: skip
async def delete_model(ctx: OpContext, inp: IdIn) -> None:
    m = await ctx.session.get(AgentModel, inp.id)
    if m is None:
        raise AppException(1001, status_code=404, detail="Model not found")
    await ctx.session.delete(m)
    await _flush(ctx, "Model")


@_studio("studio.test_provider", "Thử provider", "Gọi danh sách model của provider bằng một credential")
async def test_provider(ctx: OpContext, inp: TestProviderIn) -> TestProviderOut:
    p = await ctx.session.get(AgentProvider, inp.provider_id)
    if p is None:
        raise AppException(1001, status_code=404, detail="Provider not found")
    key = await reveal(ctx.session, inp.credential_id, ctx.settings, purpose="studio.test_provider")
    started = time.perf_counter()
    try:
        found, ms = await remote_models.fetch(
            p.kind, remote_models.base_url(p.kind, p.base_url), key, p.extra_headers or {}
        )
    except remote_models.RemoteError as exc:  # thử kết nối: lỗi trả về cho Studio, không 500
        logger.warning("thử provider %s lỗi: %s", p.name, exc.detail, extra={"loc": "agt0004"})
        error = f"HTTP {exc.status}: {exc.detail}" if exc.status else exc.detail
        return TestProviderOut(ok=False, latency_ms=int((time.perf_counter() - started) * 1000), error=error)
    return TestProviderOut(ok=True, latency_ms=ms, models=[m.model_id for m in found][:50])
