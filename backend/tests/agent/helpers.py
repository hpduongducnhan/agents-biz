"""Dựng agent + chạy lượt cho test: seed provider / model / key qua op Studio, gửi tin, chạy runner không cần broker."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlmodel import select

from app.agent.chat.models import AgentApproval, AgentMessage, AgentRun
from app.agent.config import registry
from app.agent.config.models import Agent
from app.agent.config.toolsets import toolsets
from app.agent.runtime import runner
from app.agent.runtime.tools import RunContext
from app.auth.rbac import user_permissions
from app.core.connections.registry import get_connections
from app.core.security.principal import Principal
from app.credentials.models import Credential
from app.notifications.models import Notification
from tests.auth.api import Api, Session

ROOT = "root@test.local"


@dataclass
class Stack:
    api: Api
    root: Session
    provider_id: str
    model_id: str
    cred_id: str
    agent_id: str
    base_url: str


async def get_root(api: Api) -> Session:
    """Superadmin của test (root@test.local): tạo lần đầu, các lần sau đăng nhập lại."""
    try:
        return await api.login(ROOT)
    except AssertionError:
        return await api.as_user(ROOT)


async def assistant_id() -> uuid.UUID:
    async with get_connections().postgres.ro() as s:
        return (await s.exec(select(Agent.id).where(Agent.slug == "assistant"))).one()


async def new_cred(api: Api, root: Session, provider_id: str | None, name: str, secret: str = "fake-key", **kw) -> dict:
    return await api.post("credentials.create", root, name=name, provider_id=provider_id, secret=secret, **kw)


async def setup(api: Api, base_url: str, *, key: str = "fake-key", model: str = "fake-model", **model_kw: Any) -> Stack:
    """Provider OpenAI-tương-thích trỏ LLM giả + model + 1 key, gắn vào agent "Assistant" đã seed."""
    root = await get_root(api)
    prov = await api.post("studio.save_provider", root, name="fake", kind="openai_compatible", base_url=base_url)
    mdl = await api.post("studio.save_model", root, provider_id=prov["id"], model_id=model, name=model, **model_kw)
    cred = await new_cred(api, root, prov["id"], "k1", key)
    aid = str(await assistant_id())
    current = await api.get("studio.get_agent", root, agent_id=aid)
    # "Assistant" seed là orchestrator; test agent đơn cần đủ toolset → chuyển về specialist
    await api.post("studio.save_agent", root, **save_agent_body(current, model_id=mdl["id"], kind="specialist"))
    await api.post("studio.set_toolsets", root, agent_id=aid, toolsets=list(toolsets()))
    await api.post("studio.set_agent_keys", root, agent_id=aid, keys=[{"credential_id": cred["id"]}])
    return Stack(api, root, prov["id"], mdl["id"], cred["id"], aid, base_url)


async def setup_router(api: Api, base_url: str, *, key: str = "fake-key") -> Stack:
    """Giữ "Assistant" là orchestrator (seed); gắn model + key LLM giả cho orchestrator VÀ mọi chuyên gia."""
    root = await get_root(api)
    prov = await api.post("studio.save_provider", root, name="fake", kind="openai_compatible", base_url=base_url)
    mdl = await api.post("studio.save_model", root, provider_id=prov["id"], model_id="fake-model", name="fake-model")
    cred = await new_cred(api, root, prov["id"], "k1", key)
    aid = str(await assistant_id())
    for agent in await api.get("studio.list_agents", root):
        current = await api.get("studio.get_agent", root, agent_id=agent["id"])
        await api.post("studio.save_agent", root, **save_agent_body(current, model_id=mdl["id"]))
        await api.post("studio.set_agent_keys", root, agent_id=agent["id"], keys=[{"credential_id": cred["id"]}])
    return Stack(api, root, prov["id"], mdl["id"], cred["id"], aid, base_url)


async def slug_ids() -> dict[str, uuid.UUID]:
    async with get_connections().postgres.ro() as s:
        return {slug: i for i, slug in (await s.exec(select(Agent.id, Agent.slug))).all()}


def save_agent_body(current: dict, **over: Any) -> dict:
    keep = (
        "slug name kind description instructions persona_shared starters model_id params_override "
        "recursion_limit timeout_sec key_strategy key_cooldown_sec visible_to visible_roles is_active"
    ).split()
    return {"agent_id": current["id"], **{k: current[k] for k in keep}, **over}


async def send(api: Api, who: Session, text: str, *, session_id: str | None = None, **kw: Any) -> dict:
    body = {"content": text, "client_msg_id": uuid.uuid4().hex, **kw}
    if session_id:
        body["session_id"] = session_id
    return await api.post("agent.send", who, **body)


async def chat(api: Api, who: Session, text: str, *, session_id: str | None = None) -> tuple[dict, AgentRun]:
    """Gửi tin rồi chạy lượt tại chỗ (không qua broker); trả (kết quả send, run sau khi chạy)."""
    sent = await send(api, who, text, session_id=session_id)
    await runner.execute(sent["run_id"])
    return sent, await run_row(sent["run_id"])


async def run_row(run_id: str | uuid.UUID) -> AgentRun:
    async with get_connections().postgres.ro() as s:
        return (await s.exec(select(AgentRun).where(AgentRun.id == uuid.UUID(str(run_id))))).one()


async def messages(session_id: str | uuid.UUID) -> list[AgentMessage]:
    async with get_connections().postgres.ro() as s:
        stmt = select(AgentMessage).where(AgentMessage.session_id == uuid.UUID(str(session_id)))
        return list((await s.exec(stmt.order_by(AgentMessage.seq))).all())


async def approvals(run_id: str | uuid.UUID) -> list[AgentApproval]:
    async with get_connections().postgres.ro() as s:
        stmt = select(AgentApproval).where(AgentApproval.run_id == uuid.UUID(str(run_id)))
        return list((await s.exec(stmt)).all())


def events_of(hub, user_id: str, name: str | None = None) -> list[tuple[str, dict]]:
    out = [(ev, d) for key, ev, d in hub.events() if key == f"user.{user_id}" and ev.startswith("agent:")]
    return [x for x in out if name is None or x[0] == name]


async def make_rc(who: Session, *, overrides: dict | None = None, toolsets=None, run_id=None):
    """RunContext tối thiểu cho test tool: spec "Assistant" hiện hành, principal thật của user."""

    conns = get_connections()
    async with conns.postgres.ro() as s:
        spec = await registry.load(s, conns.redis, await assistant_id())
        perms = await user_permissions(s, uuid.UUID(who.id))
    spec = replace(
        spec,
        overrides=overrides if overrides is not None else spec.overrides,
        toolsets=frozenset(toolsets) if toolsets is not None else spec.toolsets,
    )
    principal = Principal(user_id=uuid.UUID(who.id), perms=perms, sup=False)
    user = {
        "id": who.id,
        "name": "u",
        "tz": "Asia/Ho_Chi_Minh",
        "roles": ["user"],
        "is_superadmin": False,
    }
    return RunContext(run_id or uuid.uuid4(), uuid.uuid4(), user, principal, spec)


async def set_run(run_id: str | uuid.UUID, **values: Any) -> None:

    async with get_connections().postgres.rw() as s:
        await s.exec(update(AgentRun).where(AgentRun.id == uuid.UUID(str(run_id))).values(**values))


async def add_approval(
    run_id: str | uuid.UUID,
    *,
    operation: str = "notifications.mark_all_read",
    args: dict | None = None,
    status: str = "pending",
    expires_in: float = 3600,
    call_id: str | None = None,
) -> AgentApproval:
    run = await run_row(run_id)
    row = AgentApproval(
        tenant_id=run.tenant_id, run_id=run.id, tool_call_id=call_id or uuid.uuid4().hex, operation=operation,
        args=args or {}, status=status, expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )  # fmt: skip
    async with get_connections().postgres.rw() as s:
        s.add(row)
    return row


async def redis_get(key: str):
    return await get_connections().redis.rw.get(key)


async def add_keys(
    stack: Stack, secrets: list[str], *, strategy: str | None = None, weights: list[int] | None = None
) -> list[str]:
    """Thay pool key của agent bằng các credential (đúng provider của stack); trả id theo đúng thứ tự `secrets`."""
    api, root = stack.api, stack.root
    ids = []
    for i, secret in enumerate(secrets):
        extra = {"weight": weights[i]} if weights else {}
        ids.append(
            (await new_cred(api, root, stack.provider_id, f"pool-{i}-{uuid.uuid4().hex[:4]}", secret, **extra))["id"]
        )
    await api.post("studio.set_agent_keys", root, agent_id=stack.agent_id, keys=[{"credential_id": c} for c in ids])
    if strategy:
        current = await api.get("studio.get_agent", root, agent_id=stack.agent_id)
        await api.post("studio.save_agent", root, **save_agent_body(current, key_strategy=strategy))
    return ids


async def load_spec(agent_id: str | uuid.UUID):

    conns = get_connections()
    async with conns.postgres.ro() as s:
        return await registry.load(s, conns.redis, uuid.UUID(str(agent_id)))


async def credential(cred_id: str):

    async with get_connections().postgres.ro() as s:
        return await s.get(Credential, uuid.UUID(cred_id))


async def add_notes(user_id: str | uuid.UUID, count: int = 1, *, kind: str = "test") -> list[Notification]:
    """`count` thông báo chưa đọc của user — dữ liệu mẫu cho tool `notifications_*` của trợ lý."""
    rows = [Notification(user_id=uuid.UUID(str(user_id)), kind=kind, title=f"Thông báo {i + 1}") for i in range(count)]
    async with get_connections().postgres.rw() as s:
        s.add_all(rows)
    return rows


async def unread(api: Api, who: Session) -> int:
    """Số thông báo chưa đọc của user (qua API) — thay cho "số dư" khi kiểm tool ghi có chạy hay chưa."""
    return (await api.get("notifications.unread_count", who))["count"]


async def notes(user_id: str | uuid.UUID, kind: str | None = None) -> list[Notification]:
    async with get_connections().postgres.ro() as s:
        stmt = select(Notification).where(Notification.user_id == uuid.UUID(str(user_id)))
        if kind:
            stmt = stmt.where(Notification.kind == kind)
        return list((await s.exec(stmt.order_by(Notification.created_at, Notification.id))).all())
