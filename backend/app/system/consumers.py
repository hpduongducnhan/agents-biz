"""Handler messaging của miền system: nhịp tim consumer + event client `system.ping` (thử đường socket hai chiều)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.connections.registry import get_connections
from app.core.messaging.realtime import WsContext, on_ws
from app.core.messaging.streams import subscriber
from app.core.messaging.util import utc_iso
from app.system import heartbeat


@subscriber("system.ping")
async def on_ping(body: dict) -> None:
    await heartbeat.beat(get_connections().redis.rw, "consume")


class PingIn(BaseModel):
    nonce: str = Field(default="", max_length=64)


@on_ws("system.ping")
async def ws_ping(ctx: WsContext, data: PingIn) -> None:
    await ctx.reply("system:pong", {"nonce": data.nonce, "ts": utc_iso()})
