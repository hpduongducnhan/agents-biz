// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EventsPage from "@/pages/sa/EventsPage";
import IssuesPage from "@/pages/sa/IssuesPage";

import { eventItem, FP, issueRecord, issueSummary, me, page } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/observability/api", () => ({
  obsApi: { listEvents: vi.fn(), listIssues: vi.fn(), getIssue: vi.fn(), setIssueStatus: vi.fn() },
}));
const { obsApi } = await import("@/features/observability/api");

const SA = me({ is_superadmin: true, permissions: [] });
const off = { enabled: false, items: [], total: 0, limit: 20, offset: 0 };

beforeEach(() => setDesktop(true));

describe("EventsPage", () => {
  it("Mongo tắt (enabled=false) → banner, không danh sách", async () => {
    vi.mocked(obsApi.listEvents).mockResolvedValue(off);
    renderPage(<EventsPage />, { path: "/sa/events", route: "/sa/events", user: SA });
    expect((await screen.findByTestId("log-disabled-banner")).textContent).toContain("Ghi log đang tắt (MONGO_ENABLED=false)");
    expect(screen.queryByTestId("event-item-e1")).toBeNull();
  });

  it("desktop: bảng; mở một dòng → JsonView của input", async () => {
    vi.mocked(obsApi.listEvents).mockResolvedValue({ ...page([eventItem()]), enabled: true });
    renderPage(<EventsPage />, { path: "/sa/events", route: "/sa/events", user: SA });
    const row = await screen.findByTestId("event-item-e1");
    expect(row.tagName).toBe("TR");
    expect(within(row).getByText("admin.update_user")).toBeTruthy();
    await userEvent.setup().click(screen.getByTestId("event-toggle-e1"));
    const json = screen.getByTestId("event-json-e1");
    expect(within(json).getByText('"u2"')).toBeTruthy();
  });

  it("lọc theo nguồn → gọi lại từ trang đầu (debounce)", async () => {
    vi.mocked(obsApi.listEvents).mockResolvedValue({ ...page([]), enabled: true });
    renderPage(<EventsPage />, { path: "/sa/events", route: "/sa/events", user: SA });
    await userEvent.setup().selectOptions(await screen.findByTestId("events-filter-source"), "agent");
    await waitFor(() => expect(obsApi.listEvents).toHaveBeenLastCalledWith({ limit: 20, offset: 0, source: "agent" }));
  });

  it("điện thoại: thẻ, tên thao tác dài xuống dòng", async () => {
    setDesktop(false);
    vi.mocked(obsApi.listEvents).mockResolvedValue({ ...page([eventItem({ operation: "observability.set_issue_status" })]), enabled: true });
    renderPage(<EventsPage />, { path: "/sa/events", route: "/sa/events", user: SA });
    const card = await screen.findByTestId("event-item-e1");
    expect(card.tagName).toBe("LI");
    expect(within(card).getByText("observability.set_issue_status").className).toContain("break-all");
  });
});

describe("IssuesPage", () => {
  it("Mongo tắt → banner", async () => {
    vi.mocked(obsApi.listIssues).mockResolvedValue(off);
    renderPage(<IssuesPage />, { path: "/sa/issues", route: "/sa/issues", user: SA });
    expect(await screen.findByTestId("log-disabled-banner")).toBeTruthy();
  });

  it("mở chi tiết (traceback chữ thô + context JsonView), đổi trạng thái → resolved", async () => {
    vi.mocked(obsApi.listIssues).mockResolvedValue({ ...page([issueSummary()]), enabled: true });
    vi.mocked(obsApi.getIssue).mockResolvedValue({ enabled: true, item: issueRecord() });
    vi.mocked(obsApi.setIssueStatus).mockResolvedValue({ enabled: true, item: issueRecord({ status: "resolved" }) });
    renderPage(<IssuesPage />, { path: "/sa/issues", route: "/sa/issues", user: SA });
    const u = userEvent.setup();
    await u.click(await screen.findByTestId(`issue-open-${FP}`));
    const dialog = await screen.findByTestId("issue-detail");
    await waitFor(() => expect(obsApi.getIssue).toHaveBeenCalledWith(FP));
    expect(await within(dialog).findByText(/Traceback \(most recent call last\)/)).toBeTruthy();
    expect(within(dialog).getAllByTestId("json-view").length).toBeGreaterThanOrEqual(2);
    await u.selectOptions(within(dialog).getByTestId("issue-status-select"), "resolved");
    await u.click(within(dialog).getByTestId("issue-status-save"));
    await waitFor(() => expect(obsApi.setIssueStatus).toHaveBeenCalledWith(FP, "resolved"));
  });

  it("lọc 'mọi trạng thái' → bỏ tham số status", async () => {
    vi.mocked(obsApi.listIssues).mockResolvedValue({ ...page([]), enabled: true });
    renderPage(<IssuesPage />, { path: "/sa/issues", route: "/sa/issues", user: SA });
    await waitFor(() => expect(obsApi.listIssues).toHaveBeenCalledWith({ limit: 20, offset: 0, status: "open" }));
    await userEvent.setup().selectOptions(screen.getByTestId("issues-filter-status"), "");
    await waitFor(() => expect(obsApi.listIssues).toHaveBeenLastCalledWith({ limit: 20, offset: 0 }));
  });
});
