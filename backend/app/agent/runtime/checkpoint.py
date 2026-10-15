"""Checkpointer LangGraph ở Postgres schema `agent_lg` (R20): thread = `run_id`,
chỉ ghi khi graph dừng — giữ lượt đang chờ duyệt để resume ở process khác. Lượt dừng hẳn → xoá thread. Không dựng được →
None + WARNING `DEFAULTS_APPLIED=[checkpointer]` (tool cần duyệt sẽ báo chưa sẵn sàng)."""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.connections.registry import get_connections
from app.core.logging import get_logger

logger = get_logger(__name__)
SCHEMA = "agent_lg"
_state: dict = {"saver": None, "pool": None, "warned": False}


async def get_checkpointer() -> AsyncPostgresSaver | None:
    try:
        pool = await get_connections().postgres.raw_pool(
            "agent-checkpoint", search_path=SCHEMA, dict_rows=True, max_size=2
        )
        if _state["saver"] is None or _state["pool"] is not pool:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            _state.update(saver=saver, pool=pool)
        return _state["saver"]
    except Exception as exc:  # noqa: BLE001 — R20: chạy không checkpointer, báo rõ
        if not _state["warned"]:
            _state["warned"] = True
            logger.warning(
                "checkpointer agent không dựng được: %s; DEFAULTS_APPLIED=[checkpointer]", exc, extra={"loc": "agt0401"}
            )
        return None


async def drop(run_id, steps: int = 0) -> None:
    """Xoá thread của lượt: `<run_id>` (agent đơn) + `<run_id>:<i>` của từng bước chuyên gia."""
    saver = await get_checkpointer()
    if saver is not None:
        await saver.adelete_thread(str(run_id))
        for i in range(steps):
            await saver.adelete_thread(f"{run_id}:{i}")


def reset() -> None:
    _state.update(saver=None, pool=None, warned=False)
