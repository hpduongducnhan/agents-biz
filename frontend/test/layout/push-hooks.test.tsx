// @vitest-environment jsdom
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/layout/AppShell";
import { InstallGuide } from "@/layout/InstallGuide";
import { UserMenu } from "@/layout/UserMenu";
import { setTokens } from "@/lib/auth-tokens";
import { useAuthStore } from "@/lib/auth/store";
import { useLocaleStore } from "@/lib/i18n";
import { socketManager } from "@/lib/realtime/socket";
import { useUiStore } from "@/stores/ui.store";
import { TooltipProvider } from "@/ui";

import { me } from "../fixtures";
import { renderPage, testClient } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/lib/push", () => ({
  disablePush: vi.fn().mockResolvedValue(undefined),
  syncPush: vi.fn().mockResolvedValue(undefined),
  pushState: vi.fn().mockResolvedValue("unsupported"),
  enablePush: vi.fn(),
}));
vi.mock("@/features/push/api", () => ({ pushApi: { config: vi.fn().mockResolvedValue({ enabled: false, public_key: null }) } }));
vi.mock("@/features/auth/api", () => ({ authApi: { logout: vi.fn().mockResolvedValue(null), me: vi.fn(), updateMe: vi.fn() } }));
vi.mock("@/features/notifications/api", () => ({
  notificationsApi: { unreadCount: vi.fn().mockResolvedValue({ count: 0 }), list: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 }), markAllRead: vi.fn() },
  markReadFast: vi.fn(),
}));
vi.mock("@/features/wallet/api", () => ({ walletApi: { list: vi.fn().mockResolvedValue([]) }, categoryApi: { list: vi.fn().mockResolvedValue([]) } }));
vi.mock("@/features/groups/api", () => ({ groupsApi: { mine: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 }), get: vi.fn() } }));
const { disablePush, syncPush } = await import("@/lib/push");
const { authApi } = await import("@/features/auth/api");

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(disablePush).mockResolvedValue(undefined);
  vi.spyOn(socketManager, "connect").mockImplementation(() => undefined);
  vi.spyOn(socketManager, "on").mockImplementation(() => () => undefined);
});

describe("UserMenu — đăng xuất gỡ thông báo đẩy của máy", () => {
  it("gọi disablePush trước authApi.logout rồi xoá phiên", async () => {
    setTokens("a", "r");
    const order: string[] = [];
    vi.mocked(disablePush).mockImplementation(async () => void order.push("disable"));
    vi.mocked(authApi.logout).mockImplementation(async () => void order.push("logout") as never);
    renderPage(<UserMenu />);
    const u = userEvent.setup();
    await u.click(screen.getByTestId("user-menu"));
    await u.click(await screen.findByTestId("logout"));
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(false));
    expect(order).toEqual(["disable", "logout"]);
  });

  it("disablePush ném lỗi vẫn đăng xuất", async () => {
    vi.mocked(disablePush).mockRejectedValue(new Error("sw"));
    renderPage(<UserMenu />);
    const u = userEvent.setup();
    await u.click(screen.getByTestId("user-menu"));
    await u.click(await screen.findByTestId("logout"));
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(false));
  });
});

describe("AppShell — đồng bộ đăng ký push khi mở app", () => {
  it("gọi syncPush đúng một lần lúc mount", async () => {
    useLocaleStore.getState().setLocale("vi");
    useAuthStore.setState({ user: me(), isAuthenticated: true });
    render(
      <QueryClientProvider client={testClient()}>
        <TooltipProvider delayDuration={0}>
          <MemoryRouter initialEntries={["/"]}>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<div>trang chủ</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await screen.findByText("trang chủ");
    expect(syncPush).toHaveBeenCalledTimes(1);
  });
});

describe("InstallGuide — mẹo bật thông báo", () => {
  it("tab iOS có install-push-tip; tab Android cũng nhắc", async () => {
    useUiStore.setState({ installGuideOpen: true });
    renderPage(<InstallGuide />);
    const tip = await screen.findByTestId("install-push-tip");
    expect(tip.textContent).toContain("Thông báo trên máy này");
    await userEvent.setup().click(screen.getByTestId("install-tab-android"));
    await screen.findByTestId("install-steps-android");
    expect(screen.getAllByText(/Thông báo trên máy này/).length).toBeGreaterThan(0);
  });
});
