// @vitest-environment jsdom
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import NotificationsPage from "@/pages/notifications/NotificationsPage";

import { notification } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("@/features/notifications/api", () => ({
  notificationsApi: { list: vi.fn(), markAllRead: vi.fn().mockResolvedValue({ updated: 2 }) },
  markReadFast: vi.fn().mockResolvedValue(undefined),
}));
const { notificationsApi, markReadFast } = await import("@/features/notifications/api");

const page = (items: ReturnType<typeof notification>[], total = items.length) => ({ items, total, limit: 20, offset: 0 });
const LONG = "Phiếu chuyển tiền mới từ Nguyễn Thị Phương Thảo Hoàng Ngọc Bích cho quỹ chung của nhóm Nhà mẫu tháng 10";

describe("NotificationsPage", () => {
  it("điện thoại: thẻ, tiêu đề dài xuống dòng; desktop: bảng, ô cắt chữ + Tooltip (R16)", async () => {
    vi.mocked(notificationsApi.list).mockResolvedValue(page([notification({ id: "n1", title: LONG })]));
    setDesktop(false);
    const view = renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    const card = await screen.findByTestId("notif-item-n1");
    expect(card.tagName).toBe("LI");
    expect(screen.getByText(LONG).className).toContain("break-words");
    view.unmount();
    setDesktop(true);
    renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    const row = await screen.findByTestId("notif-item-n1");
    expect(row.tagName).toBe("TR");
    expect(screen.getByText(LONG).className.split(/\s+/)).toEqual(expect.arrayContaining(["block", "truncate"]));
  });

  it("đánh dấu một tin / tất cả đã đọc", async () => {
    vi.mocked(notificationsApi.list).mockResolvedValue(page([notification({ id: "n1" }), notification({ id: "n2" })]));
    setDesktop(false);
    renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("notif-read-n1"));
    expect(markReadFast).toHaveBeenCalledWith(expect.anything(), ["n1"]);
    await u.click(screen.getByTestId("notif-mark-all"));
    await waitFor(() => expect(notificationsApi.markAllRead).toHaveBeenCalled());
  });

  it("lọc chưa đọc → gọi lại từ trang đầu", async () => {
    vi.mocked(notificationsApi.list).mockResolvedValue(page([]));
    renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    expect(await screen.findByText("Chưa có thông báo")).toBeTruthy();
    await userEvent.setup().click(screen.getByTestId("notif-unread-only"));
    await waitFor(() => expect(notificationsApi.list).toHaveBeenLastCalledWith({ unread_only: true, limit: 20, offset: 0 }));
  });

  it("thông báo mới tới qua realtime (core:notification → invalidate) hiện ngay, không tải lại trang", async () => {
    vi.mocked(notificationsApi.list).mockResolvedValue(page([notification({ id: "n1", title: "Cũ" })]));
    setDesktop(false);
    const view = renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    await screen.findByText("Cũ");
    vi.mocked(notificationsApi.list).mockResolvedValue(page([notification({ id: "n2", title: "Mới tinh" }), notification({ id: "n1", title: "Cũ" })]));
    await act(() => view.client.invalidateQueries({ queryKey: ["notifications"] }));
    expect(await screen.findByTestId("notif-item-n2")).toBeTruthy();
  });
});
