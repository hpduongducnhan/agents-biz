"""observability.* — đọc event log / issues, đổi trạng thái issue (chỉ superadmin — D22). Mọi truy cập Mongo đi qua
`LogStore` (R12); tính năng log tắt → 200 `enabled: false` để UI hiện banner."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.pagination import PageIn
from app.core.operations.spec import operation
from app.observability.schemas import EventFilter, EventLogPage, IssuePage, IssueResult, IssueStatus
from app.observability.store import get_store

INVALIDATES = ("observability",)
FINGERPRINT = r"^[0-9a-f]{40}$"


class EventsIn(EventFilter, PageIn):
    pass


class IssuesIn(PageIn):
    status: IssueStatus | None = None


class IssueIn(BaseModel):
    fingerprint: str = Field(pattern=FINGERPRINT)


class IssueStatusIn(IssueIn):
    status: IssueStatus


@operation(
    name="observability.list_events",
    title="Event log",
    description="Superadmin: thao tác ghi gần đây — lọc theo người, tiền tố thao tác, nguồn, kết quả, khoảng thời gian",
    superadmin=True,
)
async def list_events(ctx: OpContext, inp: EventsIn) -> EventLogPage:
    store = get_store()
    if store is None:
        return EventLogPage(enabled=False, items=[], total=0, limit=inp.limit, offset=inp.offset)
    items, total = await store.list_events(inp, limit=inp.limit, offset=inp.offset)
    return EventLogPage(items=items, total=total, limit=inp.limit, offset=inp.offset)


@operation(
    name="observability.list_issues",
    title="Issues",
    description="Superadmin: lỗi hệ thống gom theo fingerprint, gặp gần nhất trước; lọc trạng thái",
    superadmin=True,
)
async def list_issues(ctx: OpContext, inp: IssuesIn) -> IssuePage:
    store = get_store()
    if store is None:
        return IssuePage(enabled=False, items=[], total=0, limit=inp.limit, offset=inp.offset)
    items, total = await store.list_issues(inp.status, limit=inp.limit, offset=inp.offset)
    return IssuePage(items=items, total=total, limit=inp.limit, offset=inp.offset)


@operation(
    name="observability.get_issue",
    title="Chi tiết issue",
    description="Superadmin: một issue kèm traceback mẫu (đã che) và 20 lần gặp gần nhất",
    superadmin=True,
)
async def get_issue(ctx: OpContext, inp: IssueIn) -> IssueResult:
    store = get_store()
    if store is None:
        return IssueResult(enabled=False)
    item = await store.get_issue(inp.fingerprint)
    if item is None:
        raise AppException(7002, status_code=404)
    return IssueResult(enabled=True, item=item)


@operation(
    name="observability.set_issue_status",
    title="Đổi trạng thái issue",
    description="Superadmin: open / resolved / ignored — issue resolved gặp lại sẽ tự mở lại",
    effect="write",
    superadmin=True,
    invalidates=INVALIDATES,
)
async def set_issue_status(ctx: OpContext, inp: IssueStatusIn) -> IssueResult:
    store = get_store()
    if store is None:
        return IssueResult(enabled=False)
    item = await store.set_issue_status(inp.fingerprint, inp.status, by=str(ctx.principal.user_id))
    if item is None:
        raise AppException(7002, status_code=404)
    ctx.emit_to_superadmins("data:changed", {"keys": list(INVALIDATES)})  # superadmin khác đang mở trang Issues
    return IssueResult(enabled=True, item=item)
