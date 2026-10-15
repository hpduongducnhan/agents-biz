"""studio.provider_models / studio.add_models — chọn model từ danh sách provider cung cấp (Gemini, Anthropic, OpenAI,
tương thích OpenAI) thay vì gõ tay; thêm nhiều model một lần (bỏ qua model đã có)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlmodel import select

from app.agent.config import registry, remote_models
from app.agent.config.models import AgentModel, AgentProvider
from app.agent.ops.providers import REASON, Name
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.operations.context import OpContext
from app.core.operations.spec import operation
from app.credentials.models import Credential
from app.credentials.service import reveal

logger = get_logger(__name__)
MAX_ADD = 100


class ProviderModelsIn(BaseModel):
    provider_id: uuid.UUID
    credential_id: uuid.UUID | None = Field(default=None, description="trống = key gắn provider, rồi key chưa gắn")


class RemoteModelOut(BaseModel):
    model_id: str
    name: str
    description: str
    context_window: int | None
    chat: bool
    input_price_per_1m: Decimal | None
    output_price_per_1m: Decimal | None
    cache_read_price_per_1m: Decimal | None
    added: bool


class ProviderModelsOut(BaseModel):
    credential_id: uuid.UUID
    latency_ms: int
    models: list[RemoteModelOut]


class NewModel(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    name: Name
    context_window: int | None = Field(default=None, ge=1)
    input_price_per_1m: Decimal = Field(default=Decimal(0), ge=0)
    output_price_per_1m: Decimal = Field(default=Decimal(0), ge=0)
    cache_read_price_per_1m: Decimal = Field(default=Decimal(0), ge=0)


class AddModelsIn(BaseModel):
    provider_id: uuid.UUID
    models: list[NewModel] = Field(min_length=1, max_length=MAX_ADD)


class AddModelsOut(BaseModel):
    added: int
    skipped: int


async def _provider(session, provider_id: uuid.UUID) -> AgentProvider:
    p = await session.get(AgentProvider, provider_id)
    if p is None:
        raise AppException(1001, status_code=404, detail="Provider not found")
    return p


async def _credential(session, p: AgentProvider, wanted: uuid.UUID | None) -> uuid.UUID:
    """Key gọi danh sách model: key được chọn, hoặc key đang dùng gắn với provider, rồi key chưa gắn provider nào."""
    if wanted is not None:
        return wanted
    stmt = select(Credential.id, Credential.provider_id).where(
        Credential.kind == "api_key",
        Credential.status == "active",
        (Credential.provider_id == p.id) | Credential.provider_id.is_(None),
    )
    rows = (await session.exec(stmt.order_by(Credential.created_at))).all()
    bound = [cid for cid, pid in rows if pid == p.id]
    picked = (bound or [cid for cid, _ in rows])[:1]
    if not picked:
        raise AppException(6010, status_code=409, detail="No API key for this provider — add one in Credentials")
    return picked[0]


@operation(
    "studio.provider_models",
    title="Model của provider",
    description="Danh sách model provider cung cấp (gọi API …/models bằng một key) — đánh dấu model đã thêm",
    superadmin=True,
)
async def provider_models(ctx: OpContext, inp: ProviderModelsIn) -> ProviderModelsOut:
    p = await _provider(ctx.session, inp.provider_id)
    cred = await _credential(ctx.session, p, inp.credential_id)
    key = await reveal(ctx.session, cred, ctx.settings, purpose="studio.provider_models")
    try:
        found, ms = await remote_models.fetch(
            p.kind, remote_models.base_url(p.kind, p.base_url), key, p.extra_headers or {}
        )
    except remote_models.RemoteError as exc:
        logger.warning("lấy model provider %s lỗi: %s %s", p.name, exc.status, exc.detail, extra={"loc": "agt0005"})
        raise AppException(6011, status_code=502, data={"status": exc.status, "detail": exc.detail}) from exc
    have = set((await ctx.session.exec(select(AgentModel.model_id).where(AgentModel.provider_id == p.id))).all())
    models = [RemoteModelOut(**m.__dict__, added=m.model_id in have) for m in found]
    return ProviderModelsOut(credential_id=cred, latency_ms=ms, models=models)


@operation(
    "studio.add_models",
    title="Thêm model từ provider",
    description="Thêm nhiều model một lần (tên phía provider, tên hiển thị, context, giá); model đã có thì bỏ qua",
    effect="write",
    superadmin=True,
    agent_reason=REASON,
    invalidates=("studio.models", "studio.providers"),
)
async def add_models(ctx: OpContext, inp: AddModelsIn) -> AddModelsOut:
    await _provider(ctx.session, inp.provider_id)
    have = set(
        (await ctx.session.exec(select(AgentModel.model_id).where(AgentModel.provider_id == inp.provider_id))).all()
    )
    added = 0
    for m in inp.models:
        if m.model_id in have:
            continue
        have.add(m.model_id)
        ctx.session.add(AgentModel(provider_id=inp.provider_id, **m.model_dump()))
        added += 1
    await ctx.session.flush()
    if added:
        await registry.bump(ctx.redis)
    return AddModelsOut(added=added, skipped=len(inp.models) - added)
