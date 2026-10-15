"""Handler messaging của miền giả `fx` — chỉ test import (không nằm trong DOMAINS)."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.cid import get_cid
from app.core.messaging.broadcast import on_broadcast
from app.core.messaging.realtime import WsContext, on_ws
from app.core.messaging.streams import subscriber

SEEN: list[tuple[int, str | None]] = []
BCAST: list[tuple[dict, str | None]] = []
WS: list[tuple[str, str | None]] = []


class NoteMsg(BaseModel):
    id: int


class EchoIn(BaseModel):
    text: str


@subscriber("fx.note_created")
async def on_note_created(msg: NoteMsg) -> None:
    SEEN.append((msg.id, get_cid()))


@subscriber("fx.poison")
async def on_poison(body: dict) -> None:
    raise RuntimeError("message độc")


@subscriber("fx.heavy", lane="agent-run")
async def on_heavy(body: dict) -> None:
    SEEN.append((-1, get_cid()))


@on_broadcast("fx.cache_changed")
async def on_cache_changed(data: dict) -> None:
    BCAST.append((data, get_cid()))


@on_broadcast("fx.cache_changed")
async def broken_listener(data: dict) -> None:
    raise RuntimeError("handler hỏng")


@on_ws("fx.echo", permission="fx.read")
async def ws_echo(ctx: WsContext, data: EchoIn) -> None:
    WS.append((str(ctx.principal.user_id), ctx.sid))
    await ctx.reply("fx:echo", {"text": data.text})


@on_ws("fx.crash")
async def ws_crash(ctx: WsContext, data: dict) -> None:
    raise RuntimeError("handler hỏng")
