// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OverviewPage from "@/pages/overview/OverviewPage";

import { me } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("@/features/notifications/api", async (orig) => ({
  ...(await orig<typeof import("@/features/notifications/api")>()),
  notificationsApi: { unreadCount: vi.fn() },
}));
const { notificationsApi } = await import("@/features/notifications/api");

const open = (user = me()) => renderPage(<OverviewPage />, { path: "/", route: "/", user });

beforeEach(() => {
  setDesktop(false);
  vi.mocked(notificationsApi.unreadCount).mockResolvedValue({ count: 3 });
});

describe("Tổng quan", () => {
  it("chào theo tên, lối tắt Trợ lý + Thông báo (số chưa đọc)", async () => {
    open();
    expect((await screen.findByTestId("overview-hello")).textContent).toContain("Chào Người Dùng Một");
    expect(screen.getByTestId("overview-assistant").getAttribute("href")).toBe("/assistant");
    const notif = screen.getByTestId("overview-notifications");
    expect(notif.getAttribute("href")).toBe("/notifications");
    await waitFor(() => expect(notif.textContent).toContain("3 thông báo chưa đọc"));
  });

  it("không có quyền agent.chat → không có lối tắt Trợ lý", async () => {
    open(me({ permissions: [] }));
    expect(await screen.findByTestId("overview-notifications")).toBeTruthy();
    expect(screen.queryByTestId("overview-assistant")).toBeNull();
  });

  it("chưa có tên → chào bằng email", async () => {
    open(me({ name: "" }));
    expect((await screen.findByTestId("overview-hello")).textContent).toContain("u1@test.local");
  });
});
