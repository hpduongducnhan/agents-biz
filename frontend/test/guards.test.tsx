// @vitest-environment jsdom
import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { ProtectedRoute, RequirePermission, RequireSuperadmin } from "@/guards/guards";
import { setTokens } from "@/lib/auth-tokens";
import { useAuthStore } from "@/lib/auth/store";

import { me } from "./fixtures";
import { renderPage } from "./render";

vi.mock("@/features/auth/api", () => ({ authApi: { me: vi.fn() } }));
const { authApi } = await import("@/features/auth/api");

const where = async () => (await screen.findByTestId("where")).textContent;

describe("ProtectedRoute", () => {
  it("chưa có phiên → /login?next=<đường dẫn + query hiện tại>", async () => {
    renderPage(<ProtectedRoute />, { path: "/admin/users", route: "/admin/users?q=an", user: null });
    expect(await where()).toBe(`/login?next=${encodeURIComponent("/admin/users?q=an")}`);
  });

  it("còn refresh token nhưng /auth/me bị từ chối (401) → đăng xuất, về đăng nhập", async () => {
    localStorage.setItem("bw_refresh_token", "r-cu");
    vi.mocked(authApi.me).mockRejectedValueOnce(new ApiError({ message: "unauthorized", status: 401 }));
    renderPage(<ProtectedRoute />, { path: "/profile", route: "/profile", user: null });
    expect(await where()).toMatch(/^\/login\?next=/);
    expect(localStorage.getItem("bw_refresh_token")).toBeNull();
  });

  it("/auth/me lỗi mạng → màn offline, giữ token; bấm thử lại gọi lại /auth/me rồi vào app", async () => {
    localStorage.setItem("bw_refresh_token", "r-giu");
    vi.mocked(authApi.me).mockReset();
    vi.mocked(authApi.me).mockRejectedValueOnce(new ApiError({ message: "Network error", status: 0 }));
    vi.mocked(authApi.me).mockResolvedValueOnce(me({ name: "Về lại" }));
    renderPage(<ProtectedRoute />, { path: "/", route: "/", user: null });
    expect(await screen.findByTestId("offline-screen")).toBeTruthy();
    expect(localStorage.getItem("bw_refresh_token")).toBe("r-giu");
    expect(screen.queryByTestId("where")).toBeNull();
    fireEvent.click(screen.getByTestId("offline-retry"));
    await vi.waitFor(() => expect(useAuthStore.getState().user?.name).toBe("Về lại"));
    expect(authApi.me).toHaveBeenCalledTimes(2);
  });

  it("/auth/me 5xx → cũng màn offline, không đăng xuất", async () => {
    localStorage.setItem("bw_refresh_token", "r-5xx");
    vi.mocked(authApi.me).mockReset();
    vi.mocked(authApi.me).mockRejectedValueOnce(new ApiError({ message: "bad gateway", status: 502 }));
    renderPage(<ProtectedRoute />, { path: "/", route: "/", user: null });
    expect(await screen.findByTestId("offline-screen")).toBeTruthy();
    expect(localStorage.getItem("bw_refresh_token")).toBe("r-5xx");
  });

  it("offline-screen tự thử lại khi có sự kiện online", async () => {
    localStorage.setItem("bw_refresh_token", "r-on");
    vi.mocked(authApi.me).mockReset();
    vi.mocked(authApi.me).mockRejectedValueOnce(new ApiError({ message: "Network error", status: 0 }));
    vi.mocked(authApi.me).mockResolvedValueOnce(me({ name: "Online" }));
    renderPage(<ProtectedRoute />, { path: "/", route: "/", user: null });
    await screen.findByTestId("offline-screen");
    act(() => void window.dispatchEvent(new Event("online")));
    await vi.waitFor(() => expect(useAuthStore.getState().user?.name).toBe("Online"));
  });

  it("mở lại trang chỉ với refresh token: tải /auth/me rồi mới cho vào", async () => {
    localStorage.setItem("bw_refresh_token", "r1");
    vi.mocked(authApi.me).mockResolvedValueOnce(me({ name: "Tải lại" }));
    renderPage(<ProtectedRoute />, { path: "/", route: "/", user: null });
    await vi.waitFor(() => expect(useAuthStore.getState().user?.name).toBe("Tải lại"));
    expect(screen.queryByTestId("where")).toBeNull();
  });

  it("phải đổi mật khẩu → ép sang /profile?tab=password; ở /profile thì cho ở lại", async () => {
    setTokens("ok", "r");
    const user = me({ must_change_password: true });
    vi.mocked(authApi.me).mockResolvedValue(user);
    const view = renderPage(<ProtectedRoute />, { path: "/wallets", route: "/wallets", user });
    expect(await where()).toBe("/profile?tab=password");
    view.unmount();
    renderPage(<ProtectedRoute />, { path: "/profile", route: "/profile?tab=password", user });
    expect(screen.queryByTestId("where")).toBeNull();
  });
});

describe("RequirePermission / RequireSuperadmin", () => {
  it("thiếu quyền → /403; đủ quyền hoặc superadmin → vào", async () => {
    const page = (
      <RequirePermission permission="user.view">
        <div>trang users</div>
      </RequirePermission>
    );
    const view = renderPage(page, { path: "/admin/users", route: "/admin/users" });
    expect(await where()).toBe("/403");
    view.unmount();
    renderPage(page, { path: "/admin/users", route: "/admin/users", user: me({ permissions: ["user.view"] }) });
    expect(screen.getByText("trang users")).toBeTruthy();
  });

  it("bị thu quyền khi đang ở trang admin → /403 ngay, không cần tải lại", async () => {
    renderPage(
      <RequirePermission permission="user.view">
        <div>trang users</div>
      </RequirePermission>,
      { path: "/admin/users", route: "/admin/users", user: me({ permissions: ["user.view"] }) },
    );
    expect(screen.getByText("trang users")).toBeTruthy();
    act(() => useAuthStore.setState({ user: me({ permissions: [] }) })); // như core:rbac_updated vừa tải lại me
    expect(await where()).toBe("/403");
  });

  it("RequireSuperadmin: user thường → /403; superadmin → vào", async () => {
    const view = renderPage(<RequireSuperadmin />, { path: "/sa/status", route: "/sa/status", user: me({ permissions: ["user.view", "user.manage", "role.manage"] }) });
    expect(await where()).toBe("/403");
    view.unmount();
    renderPage(<RequireSuperadmin />, { path: "/sa/status", route: "/sa/status", user: me({ is_superadmin: true }) });
    expect(screen.queryByTestId("where")).toBeNull();
  });
});
