// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { getRefreshToken } from "@/lib/auth-tokens";
import { useAuthStore } from "@/lib/auth/store";
import AuthCallbackPage from "@/pages/auth/AuthCallbackPage";
import LoginPage from "@/pages/auth/LoginPage";
import RegisterPage from "@/pages/auth/RegisterPage";
import { safeNext } from "@/pages/auth/auth-error";

import { loginResult, me, publicInfo } from "../fixtures";
import { renderPage } from "../render";

vi.mock("@/features/auth/api", () => ({ authApi: { login: vi.fn(), register: vi.fn(), me: vi.fn() } }));
vi.mock("@/features/system/api", () => ({ systemApi: { publicInfo: vi.fn() } }));
const { authApi } = await import("@/features/auth/api");
const { systemApi } = await import("@/features/system/api");

const where = async () => (await screen.findByTestId("where")).textContent;

async function fillLogin(email: string, password: string) {
  const u = userEvent.setup();
  await u.type(screen.getByLabelText("Email"), email);
  await u.type(screen.getByLabelText("Mật khẩu"), password);
  await u.click(screen.getByTestId("login-submit"));
}

describe("LoginPage", () => {
  it("đăng nhập xong quay về đúng deep link (đường dẫn + query) trong `next`", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo());
    vi.mocked(authApi.login).mockResolvedValue(loginResult(me({ permissions: ["user.view"] })));
    renderPage(<LoginPage />, { path: "/login", route: `/login?next=${encodeURIComponent("/admin/users?q=an")}`, user: null });
    await fillLogin("admin@test.local", "password123");
    expect(await where()).toBe("/admin/users?q=an");
    expect(authApi.login).toHaveBeenCalledWith({ email: "admin@test.local", password: "password123" });
    expect(useAuthStore.getState().user?.permissions).toEqual(["user.view"]);
    expect(getRefreshToken()).toBe("r1");
  });

  it("`next` trỏ ra ngoài bị bỏ → về /", async () => {
    expect(safeNext("//evil.com/x")).toBe("/");
    expect(safeNext("/\\evil.com")).toBe("/");
    expect(safeNext("https://evil.com")).toBe("/");
    expect(safeNext(null)).toBe("/");
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo());
    vi.mocked(authApi.login).mockResolvedValue(loginResult());
    renderPage(<LoginPage />, { path: "/login", route: "/login?next=%2F%2Fevil.com", user: null });
    await fillLogin("u1@test.local", "password123");
    expect(await where()).toBe("/");
  });

  it("sai mật khẩu (2102) → thông điệp tiếng Việt + Mã tra cứu, ở lại trang", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo());
    vi.mocked(authApi.login).mockRejectedValue(new ApiError({ message: "x", status: 401, code: 2102, correlationId: "cid-7" }));
    renderPage(<LoginPage />, { path: "/login", route: "/login", user: null });
    await fillLogin("u1@test.local", "sai-mat-khau");
    expect((await screen.findByRole("alert")).textContent).toContain("Sai email hoặc mật khẩu");
    expect(screen.getByTestId("error-cid").textContent).toBe("Mã tra cứu: cid-7");
  });

  it("email sai định dạng → báo cạnh ô, không gọi API", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo());
    renderPage(<LoginPage />, { path: "/login", route: "/login", user: null });
    await fillLogin("khong-phai-email", "x");
    expect(await screen.findByText("Email không hợp lệ")).toBeTruthy();
    expect(authApi.login).not.toHaveBeenCalled();
  });

  it("bị khoá giữa phiên → thông báo đầu trang; Google chỉ hiện khi bật, là link tới API", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ google_enabled: false }));
    const view = renderPage(<LoginPage />, { path: "/login", route: "/login?reason=disabled", user: null });
    expect(await screen.findByText(/Tài khoản của bạn đã bị khoá/)).toBeTruthy();
    await waitFor(() => expect(systemApi.publicInfo).toHaveBeenCalled());
    expect(screen.queryByTestId("google-login")).toBeNull();
    view.unmount();
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ google_enabled: true }));
    renderPage(<LoginPage />, { path: "/login", route: "/login", user: null });
    expect((await screen.findByTestId("google-login")).getAttribute("href")).toBe("/bizwithagents/api/auth/google/authorize");
  });
});

describe("RegisterPage", () => {
  it("đăng ký đang đóng → báo trước nhưng vẫn cho gửi (email superadmin luôn đăng ký được); 2101 → báo lỗi", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ signup_open: false }));
    vi.mocked(authApi.register).mockRejectedValue(new ApiError({ message: "x", status: 409, code: 2101, correlationId: "c-1" }));
    renderPage(<RegisterPage />, { path: "/register", route: "/register", user: null });
    expect(await screen.findByText(/Đăng ký đang đóng/)).toBeTruthy();
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Họ tên"), "Trần Văn Bình");
    await u.type(screen.getByLabelText("Email"), "binh@test.local");
    await u.type(screen.getByLabelText("Mật khẩu"), "password123");
    await u.click(screen.getByTestId("register-submit"));
    expect((await screen.findByRole("alert")).textContent).toContain("Email này đã được đăng ký");
    expect(authApi.register).toHaveBeenCalledWith({ name: "Trần Văn Bình", email: "binh@test.local", password: "password123", invite_token: null, tenant_name: null });
  });

  it("mật khẩu ngắn → báo cạnh ô; đăng ký thành công → vào app", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo());
    vi.mocked(authApi.register).mockResolvedValue(loginResult(me({ email: "moi@test.local" })));
    renderPage(<RegisterPage />, { path: "/register", route: "/register", user: null });
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Họ tên"), "Mới");
    await u.type(screen.getByLabelText("Email"), "moi@test.local");
    await u.type(screen.getByLabelText("Mật khẩu"), "1234");
    await u.click(screen.getByTestId("register-submit"));
    expect(await screen.findByText("Mật khẩu tối thiểu 8 ký tự")).toBeTruthy();
    await u.type(screen.getByLabelText("Mật khẩu"), "5678");
    await u.click(screen.getByTestId("register-submit"));
    expect(await where()).toBe("/");
    expect(useAuthStore.getState().user?.email).toBe("moi@test.local");
  });
});

describe("AuthCallbackPage (Google)", () => {
  it("token ở fragment → lưu, xoá khỏi URL, tải me, vào app", async () => {
    window.history.replaceState(null, "", "/auth/callback#access_token=a9&refresh_token=r9&token_type=bearer&expires_in=1800");
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ google_enabled: true }));
    vi.mocked(authApi.me).mockResolvedValue(me({ email: "g@test.local" }));
    renderPage(<AuthCallbackPage />, { path: "/auth/callback", route: "/auth/callback", user: null });
    expect(await where()).toBe("/");
    expect(window.location.hash).toBe("");
    expect(getRefreshToken()).toBe("r9");
    expect(useAuthStore.getState().user?.email).toBe("g@test.local");
  });

  it("Google trả lỗi (#error=2105) → về đăng nhập kèm mã", async () => {
    window.history.replaceState(null, "", "/auth/callback#error=2105");
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ google_enabled: true }));
    renderPage(<AuthCallbackPage />, { path: "/auth/callback", route: "/auth/callback", user: null });
    expect(await where()).toBe("/login?error=2105");
  });

  it("Google chưa bật → không xử lý, về đăng nhập với 2108", async () => {
    window.history.replaceState(null, "", "/auth/callback#access_token=a&refresh_token=r");
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ google_enabled: false }));
    renderPage(<AuthCallbackPage />, { path: "/auth/callback", route: "/auth/callback", user: null });
    expect(await where()).toBe("/login?error=2108");
    expect(authApi.me).not.toHaveBeenCalled();
  });
});
