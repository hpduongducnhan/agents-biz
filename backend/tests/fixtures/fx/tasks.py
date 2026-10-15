"""Task của miền giả `fx` — chỉ test import."""

from __future__ import annotations

from app.core.cid import get_cid
from app.core.messaging.tasks import task

SEEN: list[tuple[str, int, str | None]] = []


@task("fx.tally")
async def tally(n: int) -> None:
    SEEN.append(("tally", n, get_cid()))


@task("fx.slow", lane="agent-run")
async def slow(n: int) -> None:
    SEEN.append(("slow", n, get_cid()))


@task("fx.always_fail", retry=1)
async def always_fail(n: int) -> None:
    raise RuntimeError(f"hỏng {n}")


@task("fx.tick", every=1, retry=0)
async def tick() -> None:
    SEEN.append(("tick", 0, get_cid()))
