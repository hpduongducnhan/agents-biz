"""Collection Mongo: TTL chỉ trên `event_log.expire_at` (expireAfterSeconds=0); `issues` không TTL, fingerprint
duy nhất; document Beanie dùng đúng trường của record có kiểu."""

import pytest
from pymongo.errors import DuplicateKeyError

from app.core.connections.documents import init_documents
from app.observability.documents import MODELS, EventLogDoc, IssueDoc
from app.observability.schemas import EventLogRecord, IssueRecord


def test_documents_share_record_fields():
    assert set(EventLogRecord.model_fields) <= set(EventLogDoc.model_fields)
    assert set(IssueRecord.model_fields) <= set(IssueDoc.model_fields)


@pytest.mark.integration
async def test_ttl_index_only_on_event_log_expire_at(mongo_stack):
    mongo = mongo_stack.conns.mongo
    await init_documents(mongo, MODELS)
    await init_documents(mongo, MODELS)  # boot lại: không xung đột index
    events = await mongo.rw["event_log"].index_information()
    ttl = {name: spec for name, spec in events.items() if "expireAfterSeconds" in spec}
    assert list(ttl) == ["ttl_expire_at"]
    assert ttl["ttl_expire_at"]["key"] == [("expire_at", 1)] and ttl["ttl_expire_at"]["expireAfterSeconds"] == 0
    issues = await mongo.rw["issues"].index_information()
    assert not any("expireAfterSeconds" in spec for spec in issues.values())
    assert issues["uniq_fingerprint"]["unique"] is True and issues["uniq_fingerprint"]["key"] == [("fingerprint", 1)]


@pytest.mark.integration
async def test_fingerprint_is_unique(mongo_stack):
    mongo = mongo_stack.conns.mongo
    await init_documents(mongo, MODELS)
    await mongo.rw["issues"].insert_one({"fingerprint": "a" * 40})
    with pytest.raises(DuplicateKeyError):
        await mongo.rw["issues"].insert_one({"fingerprint": "a" * 40})
