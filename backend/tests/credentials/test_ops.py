"""credentials.* — superadmin, không bao giờ trả giá trị, reveal log mục đích, xoá khi đang gắn agent, xoay khoá."""

import json
import uuid

import pytest

from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.settings import active_settings
from app.credentials import crypto, service
from app.credentials.models import Credential
from tests.agent.helpers import assistant_id, get_root
from tests.fixtures.sinks import MemoryEventLog  # noqa: F401 — kiểu của memory_sinks.events

SECRET = "sk-super-secret-abcdef1234"
SA_KIND = "google_service_account"


@pytest.fixture
async def env(api, aenv, memory_sinks):
    root = await get_root(api)
    return api, root, memory_sinks


async def test_credential_ops_superadmin_only_and_never_return_secret(env):
    api, root, sinks = env
    admin = await api.as_user("adm@x.io", roles=("admin",))
    for method, op, body in (
        ("POST", "credentials.create", {"name": "k", "secret": SECRET}),
        ("GET", "credentials.list", None),
        ("POST", "credentials.update", {"credential_id": str(uuid.uuid4())}),
        ("POST", "credentials.delete", {"credential_id": str(uuid.uuid4())}),
    ):
        kw = {"json": body} if body is not None else {}
        assert await api.err(method, op, admin, **kw) == (403, 1005), op
    created = await api.post("credentials.create", root, name="openai-1", secret=SECRET, weight=5)
    assert created["masked_hint"] == "sk-…1234" and created["weight"] == 5 and created["status"] == "active"
    listed = await api.get("credentials.list", root)
    updated = await api.post("credentials.update", root, credential_id=created["id"], secret=SECRET + "x", name="o2")
    blob = json.dumps([created, listed, updated])
    assert SECRET not in blob and "secret_ciphertext" not in blob and "secret" not in created
    assert updated["name"] == "o2" and updated["masked_hint"].endswith("234x"[-4:])
    entry = next(e for e in sinks.events.entries if e.operation == "credentials.create")
    assert entry.input["secret"] == "[REDACTED]" and SECRET not in json.dumps(entry.input)


async def test_update_status_name_conflict_and_missing(env):
    api, root, _ = env
    a = await api.post("credentials.create", root, name="a", secret=SECRET)
    b = await api.post("credentials.create", root, name="b", secret=SECRET)
    off = await api.post("credentials.update", root, credential_id=a["id"], status="disabled")
    assert off["status"] == "disabled" and off["disabled_reason"]
    on = await api.post("credentials.update", root, credential_id=a["id"], status="active")
    assert on["disabled_reason"] is None
    assert await api.err("POST", "credentials.update", root, json={"credential_id": b["id"], "name": "a"}) == (
        409,
        1006,
    )
    assert await api.err("POST", "credentials.create", root, json={"name": "a", "secret": "x"}) == (409, 1006)
    missing = {"credential_id": str(uuid.uuid4())}
    assert await api.err("POST", "credentials.update", root, json=missing) == (404, 1001)
    assert await api.err("POST", "credentials.delete", root, json=missing) == (404, 1001)
    await api.post("credentials.delete", root, credential_id=b["id"])
    assert [c["name"] for c in (await api.get("credentials.list", root))["items"]] == ["a"]


async def test_list_filters_by_provider(env):
    api, root, _ = env
    prov = await api.post("studio.save_provider", root, name="p", kind="openai")
    await api.post("credentials.create", root, name="with", secret=SECRET, provider_id=prov["id"])
    await api.post("credentials.create", root, name="without", secret=SECRET)
    page = await api.get("credentials.list", root, provider_id=prov["id"])
    assert [c["name"] for c in page["items"]] == ["with"] and page["total"] == 1


async def test_list_filters_by_kind_default_api_key(env):
    api, root, _ = env
    await api.post("credentials.create", root, name="llm", secret=SECRET)
    async with get_connections().postgres.rw() as s:
        s.add(
            Credential(
                name="drive-sa", secret_ciphertext="x", key_id="k", masked_hint="h", kind="google_service_account"
            )
        )
    assert [c["name"] for c in (await api.get("credentials.list", root))["items"]] == ["llm"]
    only_sa = await api.get("credentials.list", root, kind="google_service_account")
    assert [(c["name"], c["kind"]) for c in only_sa["items"]] == [("drive-sa", "google_service_account")]
    assert only_sa["total"] == 1
    assert (await api.get("credentials.list", root, kind="api_key"))["items"][0]["kind"] == "api_key"
    assert (await api.err("GET", "credentials.list", root, params={"kind": "oauth"}))[0] == 422


async def test_reveal_logs_purpose_not_value(env, bw_log):
    api, root, _ = env
    created = await api.post("credentials.create", root, name="r", secret=SECRET)
    async with get_connections().postgres.rw() as s:
        settings = active_settings()
        assert await service.reveal(s, uuid.UUID(created["id"]), settings, purpose="unit-test") == SECRET
        with pytest.raises(AppException) as exc:
            await service.reveal(s, uuid.uuid4(), settings, purpose="x")
        assert exc.value.code == 1001
    lines = [r for r in bw_log() if r.get("loc") == "cred0002"]
    assert len(lines) == 1 and "purpose=unit-test" in lines[0]["msg"] and created["id"] in lines[0]["msg"]
    assert SECRET not in json.dumps(bw_log())


async def test_prod_without_keys_ops_are_6016(env, aenv):
    api, root, _ = env
    aenv.CREDENTIAL_KEYS, aenv.ENV = "", "prod"
    try:
        assert await api.err("POST", "credentials.create", root, json={"name": "p", "secret": SECRET}) == (503, 6016)
    finally:
        aenv.ENV = "dev"


async def test_delete_in_use_is_6016(env):
    api, root, _ = env
    cred = await api.post("credentials.create", root, name="inuse", secret=SECRET)
    aid = str(await assistant_id())
    await api.post("studio.set_agent_keys", root, agent_id=aid, keys=[{"credential_id": cred["id"]}])
    assert await api.err("POST", "credentials.delete", root, json={"credential_id": cred["id"]}) == (409, 6016)
    await api.post("studio.set_agent_keys", root, agent_id=aid, keys=[])
    await api.post("credentials.delete", root, credential_id=cred["id"])


async def test_rotate_all_reencrypts_with_first_key(env, aenv):
    api, root, _ = env
    old = aenv.CREDENTIAL_KEYS
    created = await api.post("credentials.create", root, name="rot", secret=SECRET)
    new = crypto.new_key()
    aenv.CREDENTIAL_KEYS = f"{new},{old}"
    async with get_connections().postgres.rw() as s:
        assert await service.rotate_all(s, aenv) == 1
        assert await service.rotate_all(s, aenv) == 0  # đã đổi rồi
    async with get_connections().postgres.ro() as s:
        row = await s.get(Credential, uuid.UUID(created["id"]))
        assert row.key_id == crypto.key_id(new.encode())
        assert crypto.decrypt(row.secret_ciphertext, aenv) == SECRET
