// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { notifUrl } from "@/features/notifications/notif";
import { NotificationBell } from "@/layout/NotificationBell";
import NotificationsPage from "@/pages/notifications/NotificationsPage";

import { notification } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("@/features/notifications/api", () => ({
  notificationsApi: { list: vi.fn(), unreadCount: vi.fn(), markAllRead: vi.fn() },
  markReadFast: vi.fn().mockResolvedValue(undefined),
}));
const { notificationsApi, markReadFast } = await import("@/features/notifications/api");

const LINK = "https://drive.google.com/file/d/abc123/view";
const done = (over = {}) =>
  notification({
    id: "d1", kind: "drive_export_done", title: "Đã xuất users.csv lên Drive", params: { kind: "users", name: "users.csv", link: LINK },
    action: { kind: "url", url: LINK, label: "Mở trên Drive" }, ...over,
  }); // fmt: skip
const page = (items: ReturnType<typeof notification>[]) => ({ items, total: items.length, limit: 20, offset: 0 });

describe("notifUrl", () => {
  it("chỉ nhận action kind=url với https", () => {
    expect(notifUrl({ action: { kind: "url", url: LINK, label: "Mở" } })).toEqual({ url: LINK, label: "Mở" });
    expect(notifUrl({ action: { kind: "url", url: LINK } })).toEqual({ url: LINK, label: "" });
    for (const action of [null, undefined, {}, { kind: "link", to: "/x" }, { kind: "url", url: "http://x.io" }, { kind: "url", url: "javascript:alert(1)" }, { kind: "url" }, { kind: "url", url: 5 }])
      expect(notifUrl({ action })).toBeNull();
  });
});

describe("NotificationsPage — link ngoài", () => {
  beforeEach(() => setDesktop(false));

  it("có nút mở link: href https, target=_blank, rel noopener; tiêu đề dịch theo kind", async () => {
    vi.mocked(notificationsApi.list).mockResolvedValue(page([done()]));
    renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    const a = (await screen.findByTestId("notif-url-d1")) as HTMLAnchorElement;
    expect(a.getAttribute("href")).toBe(LINK);
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("rel")).toContain("noopener");
    expect(a.textContent).toContain("Mở trên Drive");
    expect(screen.getByText("Đã xuất users.csv lên Drive")).toBeTruthy();
  });

  it("bấm link → đánh dấu đã đọc; không có label → nhãn mặc định", async () => {
    vi.mocked(notificationsApi.list).mockResolvedValue(page([done({ action: { kind: "url", url: LINK } })]));
    renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    const a = await screen.findByTestId("notif-url-d1");
    expect(a.textContent?.trim().length).toBeGreaterThan(0);
    a.addEventListener("click", (e) => e.preventDefault()); // jsdom không điều hướng
    await userEvent.setup().click(a);
    expect(markReadFast).toHaveBeenCalledWith(expect.anything(), ["d1"]);
  });

  it("action http:// → không có nút", async () => {
    vi.mocked(notificationsApi.list).mockResolvedValue(page([done({ action: { kind: "url", url: "http://evil.io" } })]));
    renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    await screen.findByTestId("notif-item-d1");
    expect(screen.queryByTestId("notif-url-d1")).toBeNull();
  });
});

describe("NotificationBell — link ngoài", () => {
  const open = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("open", open);
    vi.mocked(notificationsApi.unreadCount).mockResolvedValue({ count: 1 });
    vi.mocked(notificationsApi.list).mockResolvedValue(page([done()]));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("chọn thông báo có link → mở tab mới noopener, đánh dấu đã đọc, không điều hướng trong app", async () => {
    renderPage(<NotificationBell />);
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("notification-bell"));
    await u.click(await screen.findByText("Đã xuất users.csv lên Drive"));
    await waitFor(() => expect(open).toHaveBeenCalledWith(LINK, "_blank", "noopener,noreferrer"));
    expect(markReadFast).toHaveBeenCalledWith(expect.anything(), ["d1"]);
    expect(screen.queryByTestId("where")).toBeNull();
  });

  it("thông báo không có link → không mở tab", async () => {
    vi.mocked(notificationsApi.list).mockResolvedValue(page([notification({ id: "n9", title: "Chỉ chữ" })]));
    renderPage(<NotificationBell />);
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("notification-bell"));
    await u.click(await screen.findByText("Chỉ chữ"));
    expect(open).not.toHaveBeenCalled();
  });
});
