// @vitest-environment jsdom
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, type RouteObject, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { routes } from "@/boot/router";
import { setTokens } from "@/lib/auth-tokens";
import { useAuthStore } from "@/lib/auth/store";
import { socketManager } from "@/lib/realtime/socket";
import { TooltipProvider } from "@/ui";

import { adminUser, loginResult, me, page, publicInfo } from "../fixtures";
import { setDesktop, testClient } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/auth/api", () => ({ authApi: { login: vi.fn(), register: vi.fn(), me: vi.fn(), logout: vi.fn(), updateMe: vi.fn() } }));
vi.mock("@/features/admin/api", () => ({ adminApi: { listUsers: vi.fn() } }));
vi.mock("@/features/system/api", () => ({ systemApi: { publicInfo: vi.fn() } }));
vi.mock("@/features/notifications/api", () => ({
  notificationsApi: { unreadCount: vi.fn().mockResolvedValue({ count: 0 }), list: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 }) },
  markReadFast: vi.fn(),
}));
const { authApi } = await import("@/features/auth/api");
const { adminApi } = await import("@/features/admin/api");
const { systemApi } = await import("@/features/system/api");

function paths(list: RouteObject[], base = ""): string[] {
  return list.flatMap((r) => {
    const here = r.index ? base || "/" : r.path ? (r.path.startsWith("/") ? r.path : `${base}/${r.path}`) : base;
    return [...(r.index || r.path ? [here] : []), ...paths(r.children ?? [], here === "/" ? "" : here)];
  });
}

function boot(entry: string) {
  const router = createMemoryRouter(routes, { initialEntries: [entry] });
  render(
    <QueryClientProvider client={testClient()}>
      <TooltipProvider delayDuration={0}>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return router;
}

beforeEach(() => {
  useAuthStore.setState({ user: null, isAuthenticated: false });
  vi.spyOn(socketManager, "connect").mockImplementation(() => undefined);
  vi.spyOn(socketManager, "on").mockImplementation(() => () => undefined);
  vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo());
  setDesktop(false);
});

describe("routes", () => {
  it("đủ route của khung nền", () => {
    expect(paths(routes)).toEqual(
      expect.arrayContaining([
        "/login", "/register", "/auth/callback", "/", "/assistant", "/notifications", "/profile", "/403",
        "/admin/users", "/admin/roles", "/sa/status", "/sa/events", "/sa/issues", "/sa/settings", "/studio", "/sa/traces", "/sa/traces/:id", "/sa/usage", "/sa/chat-guard", "/*",
      ]),
    );
  });

  it("deep link khi chưa đăng nhập → /login?next=… → đăng nhập → đúng trang + query, trang gọi API với q", async () => {
    const admin = me({ permissions: ["user.view"] });
    vi.mocked(authApi.login).mockResolvedValue(loginResult(admin));
    vi.mocked(authApi.me).mockResolvedValue(admin);
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([adminUser()]));
    const router = boot("/admin/users?q=an");
    const u = userEvent.setup();
    await u.type(await screen.findByTestId("login-email"), "admin@test.local");
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toBe(`?next=${encodeURIComponent("/admin/users?q=an")}`);
    await u.type(screen.getByTestId("login-password"), "password123");
    await u.click(screen.getByTestId("login-submit"));
    await waitFor(() => expect(`${router.state.location.pathname}${router.state.location.search}`).toBe("/admin/users?q=an"));
    await waitFor(() => expect(adminApi.listUsers).toHaveBeenCalledWith({ q: "an", limit: 20, offset: 0 }));
  });

  it("/ (Tổng quan) cũng bắt đăng nhập", async () => {
    const router = boot("/");
    await screen.findByTestId("login-submit");
    expect(`${router.state.location.pathname}${router.state.location.search}`).toBe("/login?next=%2F");
  });

  it("user thường gõ thẳng /sa/status → /403", async () => {
    setTokens("a1", "r1");
    vi.mocked(authApi.me).mockResolvedValue(me());
    const router = boot("/sa/status");
    expect(await screen.findByTestId("page-forbidden")).toBeTruthy();
    expect(router.state.location.pathname).toBe("/403");
  });

  it("App dựng router trình duyệt thật + Toaster; /register mở không cần phiên", async () => {
    window.history.replaceState(null, "", "/register");
    const { App } = await import("@/App");
    render(<App />);
    expect(await screen.findByTestId("register-submit")).toBeTruthy();
  });
});
