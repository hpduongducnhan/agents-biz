// @vitest-environment jsdom
import { QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/layout/AppShell";
import { Titled } from "@/layout/Titled";
import { setTokens } from "@/lib/auth-tokens";
import type { Me } from "@/lib/auth/types";
import { useAuthStore } from "@/lib/auth/store";
import { useLocaleStore } from "@/lib/i18n";
import { socketManager, useSocketStatusStore } from "@/lib/realtime/socket";
import { useUiStore } from "@/stores/ui.store";
import { TooltipProvider } from "@/ui";

import { me } from "../fixtures";
import { testClient, Where } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/notifications/api", async () => {
  const { notification } = await import("../fixtures");
  return {
    notificationsApi: {
      unreadCount: vi.fn().mockResolvedValue({ count: 12 }),
      list: vi
        .fn()
        .mockResolvedValue({
          items: [notification({ id: "n1", title: "Phiếu mới từ An" })],
          total: 1,
          limit: 10,
          offset: 0,
        }),
      markAllRead: vi.fn().mockResolvedValue({ updated: 12 }),
    },
    markReadFast: vi.fn().mockResolvedValue(undefined),
  };
});
vi.mock("@/features/wallet/api", () => ({
  walletApi: { list: vi.fn().mockResolvedValue([]) },
  categoryApi: { list: vi.fn().mockResolvedValue([]) },
}));
vi.mock("@/features/groups/api", () => ({
  groupsApi: {
    mine: vi
      .fn()
      .mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 }),
    get: vi.fn(),
  },
}));
vi.mock("@/features/auth/api", async () => {
  const { me: fake } = await import("../fixtures");
  return {
    authApi: {
      logout: vi.fn().mockResolvedValue(null),
      me: vi.fn(),
      updateMe: vi.fn().mockResolvedValue(fake({ locale: "en" })),
    },
  };
});
const { markReadFast } = await import("@/features/notifications/api");
const { authApi } = await import("@/features/auth/api");

const classes = (el: Element) => el.className.split(/\s+/);

function shell(user: Me = me()) {
  useLocaleStore.getState().setLocale("vi");
  useAuthStore.setState({ user, isAuthenticated: true });
  return render(
    <QueryClientProvider client={testClient()}>
      <TooltipProvider delayDuration={0}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route
                index
                element={
                  <Titled title="nav.overview">
                    <div>trang chủ</div>
                  </Titled>
                }
              />
            </Route>
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(socketManager, "connect").mockImplementation(() => undefined);
  vi.spyOn(socketManager, "on").mockImplementation(() => () => undefined);
  useUiStore.setState({
    sidebarCollapsed: false,
    navGroups: {},
  });
});

describe("AppShell — bố cục theo kích thước (class-based)", () => {
  it("dưới md: cụm nút nổi giữa đáy + nút ☰ + logo trên header; từ md: sidebar + cụm công cụ header", async () => {
    shell();
    expect(classes(await screen.findByTestId("sidebar"))).toEqual(
      expect.arrayContaining(["hidden", "md:flex"]),
    );
    expect(screen.queryByTestId("bottom-tabs")).toBeNull();
    expect(classes(screen.getByTestId("mobile-dock"))).toEqual(
      expect.arrayContaining(["fixed", "justify-center", "md:hidden"]),
    );
    expect(classes(screen.getByTestId("nav-open"))).toContain("md:hidden");
    expect(
      classes(screen.getByTestId("header-logo").parentElement as HTMLElement),
    ).toContain("md:hidden");
    expect(classes(screen.getByTestId("header-tools"))).toEqual(
      expect.arrayContaining(["hidden", "md:flex"]),
    );
    expect(screen.getByTestId("page-title").textContent).toBe("Tổng quan");
  });

  it("cụm nút nổi có Trợ lý, cao ≥ 48px", async () => {
    shell();
    const dock = await screen.findByTestId("mobile-dock");
    const items = [...dock.querySelectorAll("a,button")];
    expect(items.map((e) => e.getAttribute("data-testid"))).toEqual(["dock-assistant"]);
    expect(items[0]?.textContent).toBe("Trợ lý");
    for (const e of items) expect(classes(e)).toContain("h-12");
  });

  it("sidebar theo quyền: user thường không có Quản trị; admin thấy Users / Roles; superadmin thấy 4 trang hệ thống", async () => {
    const view = shell();
    let side = await screen.findByTestId("sidebar");
    expect(within(side).queryByText("Người dùng")).toBeNull();
    expect(within(side).queryByText("Trạng thái")).toBeNull();
    view.unmount();
    const admin = shell(
      me({ permissions: ["user.view", "user.manage", "role.manage"] }),
    );
    side = await screen.findByTestId("sidebar");
    expect(within(side).getByText("Người dùng")).toBeTruthy();
    expect(within(side).getByText("Role hệ thống")).toBeTruthy();
    expect(within(side).queryByText("Trạng thái")).toBeNull();
    admin.unmount();
    shell(me({ is_superadmin: true, permissions: [] }));
    side = await screen.findByTestId("sidebar");
    for (const label of [
      "Người dùng",
      "Role hệ thống",
      "Observability",
      "Cấu hình hệ thống",
      "AI",
    ]) {
      expect(within(side).getByText(label)).toBeTruthy();
    }
    const u = userEvent.setup();
    for (const k of ["observability", "config"])
      await u.click(screen.getByTestId(`nav-group-${k}`));
    for (const label of [
      "Trạng thái",
      "Nhật ký sự kiện",
      "Issues",
      "Cài đặt hệ thống",
    ])
      expect(within(side).getByText(label)).toBeTruthy();
    for (const id of [
      "users",
      "roles",
      "status",
      "events",
      "issues",
      "settings",
    ])
      expect(screen.getByTestId(`nav-${id}`)).toBeTruthy();
  });

  it("dưới md: trang quản trị nằm trong ngăn kéo ☰, menu người dùng không còn mục điều hướng", async () => {
    shell(me({ permissions: ["user.view"] }));
    await userEvent.setup().click(await screen.findByTestId("nav-open"));
    const drawer = await screen.findByTestId("nav-drawer");
    expect(within(drawer).getByTestId("nav-users")).toBeTruthy();
    await userEvent.setup().keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("nav-drawer")).toBeNull());
    await userEvent.setup().click(screen.getByTestId("user-menu"));
    await screen.findByTestId("logout");
    expect(screen.queryByTestId("menu-users")).toBeNull();
  });

  it("chuông: đếm 9+, mở xem, bấm thông báo → đánh dấu đã đọc", async () => {
    shell();
    expect((await screen.findByTestId("notification-count")).textContent).toBe(
      "9+",
    );
    await userEvent.setup().click(screen.getByTestId("notification-bell"));
    await userEvent.setup().click(await screen.findByText("Phiếu mới từ An"));
    await waitFor(() =>
      expect(markReadFast).toHaveBeenCalledWith(expect.anything(), ["n1"]),
    );
  });

  it("đèn socket theo trạng thái kết nối", async () => {
    shell();
    const dot = await screen.findByTestId("socket-dot");
    act(() => useSocketStatusStore.setState({ status: "connected" }));
    expect(dot.getAttribute("data-status")).toBe("connected");
    act(() => useSocketStatusStore.setState({ status: "offline" }));
    expect(dot.getAttribute("data-status")).toBe("offline");
  });

  it("tên / email rất dài: header và menu không đẩy bề ngang (truncate / break-all, cha min-w-0)", async () => {
    const longName =
      "Nguyễn Thị Phương Thảo Hoàng Ngọc Bích Trần Lê Minh Khuê Đặng Vũ Quỳnh Như";
    const longEmail =
      "nguyen.thi.phuong.thao.hoang.ngoc.bich.rat.dai@mot-ten-mien-rat-dai.example.vn";
    shell(me({ name: longName, email: longEmail }));
    const title = await screen.findByTestId("page-title");
    expect(classes(title)).toContain("truncate");
    expect(classes(title.parentElement as HTMLElement)).toContain("min-w-0");
    await userEvent.setup().click(screen.getByTestId("user-menu"));
    expect(classes(await screen.findByTestId("user-menu-name"))).toContain(
      "truncate",
    );
    expect(classes(screen.getByTestId("user-menu-email"))).toContain(
      "break-all",
    );
    expect(screen.getByTestId("user-menu-name").textContent).toBe(longName);
  });

  it("header: đổi theme vòng system → light → dark; đổi ngôn ngữ lưu vào hồ sơ", async () => {
    useUiStore.setState({ theme: "system" });
    shell();
    fireEvent.click(await screen.findByTestId("theme-toggle"));
    expect(useUiStore.getState().theme).toBe("light");
    fireEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(screen.getByTestId("lang-en"));
    expect(useLocaleStore.getState().locale).toBe("en");
    expect(await screen.findAllByText("Overview")).not.toHaveLength(0);
    await waitFor(() =>
      expect(authApi.updateMe).toHaveBeenCalledWith({ locale: "en" }),
    );
  });

  it("đăng xuất: gọi API với refresh token rồi về /login", async () => {
    setTokens("a1", "r9");
    shell();
    await userEvent.setup().click(await screen.findByTestId("user-menu"));
    await userEvent.setup().click(await screen.findByTestId("logout"));
    await waitFor(() => expect(authApi.logout).toHaveBeenCalledWith("r9"));
    expect((await screen.findByTestId("where")).textContent).toBe("/login");
  });

  it("thu gọn sidebar", async () => {
    shell();
    fireEvent.click(await screen.findByLabelText("Thu gọn"));
    expect(useUiStore.getState().sidebarCollapsed).toBe(true);
  });
});
