"""push.* — bật / tắt thông báo đẩy trên một máy. Chỉ giao diện: trợ lý không cần."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlmodel import select

from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.spec import operation
from app.notifications.models import PushSubscription
from app.notifications.push import allowed_endpoint, enabled, public_key, valid_keys

REASON = "bật / tắt thông báo đẩy của trình duyệt — chỉ trên giao diện"


class PushConfigOut(BaseModel):
    enabled: bool
    public_key: str | None


class SubKeys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=200)
    auth: str = Field(min_length=16, max_length=100)


class SubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: SubKeys
    user_agent: str = Field(default="", max_length=300)


class SubscribeOut(BaseModel):
    id: uuid.UUID


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)


class UnsubscribeOut(BaseModel):
    removed: int


@operation(
    "push.config", title="Cấu hình thông báo đẩy", description="Máy chủ có bật Web Push không + khoá VAPID công khai"
)
async def config(ctx: OpContext) -> PushConfigOut:
    if not enabled(ctx.settings):
        return PushConfigOut(enabled=False, public_key=None)
    return PushConfigOut(enabled=True, public_key=await public_key(ctx.settings))


@operation(
    "push.subscribe",
    title="Bật thông báo đẩy",
    description="Lưu đăng ký Web Push của trình duyệt này cho tài khoản đang đăng nhập (máy đổi tài khoản → gán lại)",
    effect="write",
    agent_reason=REASON,
)
async def subscribe(ctx: OpContext, inp: SubscribeIn) -> SubscribeOut:
    if not enabled(ctx.settings):
        raise AppException(1003, status_code=409, detail="Web Push is not enabled on this server")
    if not allowed_endpoint(inp.endpoint) or not valid_keys(inp.keys.p256dh, inp.keys.auth):
        raise AppException(1002, status_code=422, detail="Unsupported push endpoint or keys")
    me = ctx.principal.user_id
    row = (await ctx.session.exec(select(PushSubscription).where(PushSubscription.endpoint == inp.endpoint))).first()
    if row is None:
        row = PushSubscription(user_id=me, endpoint=inp.endpoint, p256dh=inp.keys.p256dh, auth=inp.keys.auth)
    row.user_id, row.p256dh, row.auth, row.user_agent, row.failures = (
        me,
        inp.keys.p256dh,
        inp.keys.auth,
        inp.user_agent,
        0,
    )
    ctx.session.add(row)
    await ctx.session.flush()
    return SubscribeOut(id=row.id)


@operation(
    "push.unsubscribe",
    title="Tắt thông báo đẩy",
    description="Gỡ đăng ký Web Push của trình duyệt này (đăng xuất cũng gọi)",
    effect="write",
    agent_reason=REASON,
)
async def unsubscribe(ctx: OpContext, inp: UnsubscribeIn) -> UnsubscribeOut:
    stmt = delete(PushSubscription).where(
        PushSubscription.endpoint == inp.endpoint, PushSubscription.user_id == ctx.principal.user_id
    )
    result = await ctx.session.exec(stmt)
    return UnsubscribeOut(removed=result.rowcount or 0)
