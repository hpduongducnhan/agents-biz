"""MongoDB — 2 AsyncMongoClient RW / RO; handle RO chỉ lộ API đọc."""

from __future__ import annotations

from collections.abc import Mapping

from pymongo import AsyncMongoClient, ReadPreference
from pymongo.asynchronous.database import AsyncDatabase

from app.core.settings import Settings

READ_METHODS = frozenset(
    {
        "find",
        "find_one",
        "count_documents",
        "estimated_document_count",
        "distinct",
        "list_indexes",
        "index_information",
    }
)

WRITE_STAGES = frozenset({"$out", "$merge"})


class ReadOnlyCollection:
    def __init__(self, collection) -> None:
        self._c = collection

    @property
    def name(self) -> str:
        return self._c.name

    async def aggregate(self, pipeline, *args, **kwargs):
        """Pipeline có stage `$out` / `$merge` là ghi — chặn trước khi tới server."""
        if any(isinstance(stage, Mapping) and stage.keys() & WRITE_STAGES for stage in pipeline):
            raise PermissionError("Mongo RO không cho aggregate với $out / $merge — dùng kênh RW")
        return await self._c.aggregate(pipeline, *args, **kwargs)

    def __getattr__(self, attr: str):
        if attr in READ_METHODS:
            return getattr(self._c, attr)
        raise AttributeError(f"Mongo RO không cho '{attr}' — dùng kênh RW")


class ReadOnlyDatabase:
    def __init__(self, db: AsyncDatabase) -> None:
        self._db = db

    @property
    def name(self) -> str:
        return self._db.name

    def __getitem__(self, name: str) -> ReadOnlyCollection:
        return ReadOnlyCollection(self._db[name])

    def get_collection(self, name: str) -> ReadOnlyCollection:
        return self[name]

    async def list_collection_names(self) -> list[str]:
        return await self._db.list_collection_names()


class Mongo:
    def __init__(self, settings: Settings) -> None:
        self.rw_client: AsyncMongoClient = AsyncMongoClient(settings.MONGO_RW_URL, tz_aware=True)
        self.ro_client: AsyncMongoClient = AsyncMongoClient(settings.mongo_ro_url, tz_aware=True)
        self.rw: AsyncDatabase = self.rw_client[settings.MONGO_DB_NAME]
        self.rw_read_only = ReadOnlyDatabase(self.rw)  # operation read cần đọc kênh RW (`read_from="rw"`)
        self.ro = ReadOnlyDatabase(
            self.ro_client.get_database(settings.MONGO_DB_NAME, read_preference=ReadPreference.SECONDARY_PREFERRED)
        )

    async def ping(self, channel: str) -> None:
        client = self.rw_client if channel == "rw" else self.ro_client
        await client.admin.command("ping")

    async def close(self) -> None:
        await self.rw_client.close()
        await self.ro_client.close()
