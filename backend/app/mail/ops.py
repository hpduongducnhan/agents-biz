"""mail.* — superadmin xem thư transport `console` đã "gửi" (dev / stack thử); transport khác → `enabled: false`."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.operations.context import OpContext
from app.core.operations.spec import operation
from app.mail.schemas import OutboxOut
from app.mail.transport import read_outbox


class OutboxIn(BaseModel):
    limit: int = Field(default=20, ge=1, le=50)


@operation(
    "mail.outbox",
    title="Hộp thư console",
    description="Superadmin: thư gần nhất transport `console` đã ghi (chỉ có khi MAIL_TRANSPORT khác smtp)",
    superadmin=True,
    agent_reason="công cụ quản trị, chỉ superadmin trên giao diện",
)
async def outbox(ctx: OpContext, inp: OutboxIn) -> OutboxOut:
    if ctx.settings.MAIL_TRANSPORT == "smtp" and ctx.settings.SMTP_HOST:
        return OutboxOut(enabled=False)
    return OutboxOut(enabled=True, items=await read_outbox(inp.limit))
