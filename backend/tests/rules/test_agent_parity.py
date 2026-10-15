"""Parity web ↔ agent: operation ghi của miền phía user (notifications)
phải `agent=True`, hoặc `agent=False` kèm `agent_reason`."""

from app.core.operations.registry import all_specs
from app.core.operations.spec import OperationSpec
from app.domains import load_domains

USER_DOMAINS = frozenset({"notifications"})


def parity_violations(specs) -> list[str]:
    return sorted(
        s.name
        for s in specs
        if s.package in USER_DOMAINS and s.effect != "read" and not s.agent and not (s.agent_reason or "").strip()
    )


async def _noop(ctx):
    return None


def make_spec(name: str, source: str, *, effect="write", agent=False, agent_reason=None) -> OperationSpec:
    return OperationSpec(
        name=name,
        func=_noop,
        input_model=None,
        output_model=None,
        takes_input=False,
        title="x",
        description="",
        http=None,
        effect=effect,
        permission=None,
        superadmin=False,
        public=False,
        agent=agent,
        toolset="lookup" if agent else None,
        agent_reason=agent_reason,
        agent_hint=None,
        invalidates=(),
        read_from="ro",
        status_code=200,
        source=source,
        sup_all_tenants=False,
    )


def test_user_domain_writes_are_open_to_agent_or_explain_why():
    load_domains()
    assert parity_violations(all_specs()) == []


def test_checker_flags_only_unexplained_user_domain_writes():
    specs = [
        make_spec("notifications.record", "app.notifications.ops"),  # vi phạm
        make_spec("notifications.mark", "app.notifications.ops", agent=True),
        make_spec("notifications.export_csv", "app.notifications.ops", agent_reason="tải file — chỉ UI"),
        make_spec("notifications.list_all", "app.notifications.ops", effect="read"),
        make_spec("notifications.purge", "app.notifications.ops", effect="destructive"),  # vi phạm
        make_spec("admin.list_users", "app.auth.ops"),  # auth không thuộc miền phía user
        make_spec("notifications.clear", "app.notifications.ops", agent_reason="  "),  # lý do rỗng = vi phạm
    ]
    assert parity_violations(specs) == ["notifications.clear", "notifications.purge", "notifications.record"]
