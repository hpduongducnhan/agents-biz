"""Lane → queue taskiq cố định trên MỘT broker (B3). Không file topology: thêm lane = sửa dict này."""

from __future__ import annotations

from app.core.messaging.names import TQ_DEFAULT_QUEUE

LANES: dict[str, str] = {
    "default": TQ_DEFAULT_QUEUE,
    "agent-run": "bw.tq.agent-run",
}


def check_lane(lane: str) -> str:
    if lane not in LANES:
        raise ValueError(f"lane '{lane}' không có trong LANES ({', '.join(LANES)})")
    return lane


def task_queue(lane: str) -> str:
    return LANES[check_lane(lane)]


def parse_lanes(value: str | None) -> list[str] | None:
    """`--lanes a,b` của `bw consume` / `bw work`; trống = mọi lane. Lane lạ → lỗi (gõ sai không được im lặng)."""
    names = [x.strip() for x in (value or "").split(",") if x.strip()]
    return [check_lane(x) for x in names] or None
