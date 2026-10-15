"""Beanie: gắn Document vào database Mongo kênh RW (chỉ khi MONGO_ENABLED)."""

from __future__ import annotations

from beanie import init_beanie

from app.core.connections.mongo import Mongo
from app.core.logging import get_logger

logger = get_logger(__name__)


async def init_documents(mongo: Mongo, models: list[type]) -> None:
    """Document ghi / đọc qua kênh RW; đọc nặng muốn đi RO thì dùng `conns.mongo.ro` (collection thô)."""
    if not models:
        return
    await init_beanie(database=mongo.rw, document_models=models)
    logger.info("beanie sẵn sàng: %s", sorted(m.Settings.name for m in models), extra={"loc": "db0010"})
