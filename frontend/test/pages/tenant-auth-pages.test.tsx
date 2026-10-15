// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VerifyBanner } from "@/layout/VerifyBanner";
import { ApiError } from "@/lib/api";
import { useAuthStore } from "@/lib/auth/store";
import ForgotPasswordPage from "@/pages/auth/ForgotPasswordPage";
import InvitePage from "@/pages/auth/InvitePage";
import RegisterPage from "@/pages/auth/RegisterPage";
import ResetPasswordPage from "@/pages/auth/ResetPasswordPage";
import VerifyEmailPage from "@/pages/auth/VerifyEmailPage";

import { loginResult, me, publicInfo } from "../fixtures";
import { renderPage } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/auth/api", () => ({
  authApi: { register: vi.fn(), requestVerify: vi.fn(), verifyEmail: vi.fn(), forgotPassword: vi.fn(), resetPassword: vi.fn() },
}));
vi.mock("@/features/system/api", () => ({ systemApi: { publicInfo: vi.fn() } }));
vi.mock("@/features/tenant/api", () => ({ tenantApi: { preview: vi.fn() } }));
const { authApi } = await import("@/features/auth/api");
const { systemApi } = await import("@/features/system/api");
const { tenantApi } = await import("@/features/tenant/api");

const expired = () => new ApiError({ message: "x", status: 400, code: 2114, correlationId: "c-9" });

describe("RegisterPage — theo signup_mode / email_verification (D12, D14)", () => {
  it("new_tenant → hỏi tên tổ chức và gửi kèm", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ signup_mode: "new_tenant" }));
    vi.mocked(authApi.register).mockResolvedValue(loginResult());
    renderPage(<RegisterPage />, { path: "/register", route: "/register", user: null });
    const u = userEvent.setup();
    await u.type(await screen.findByTestId("register-tenant"), "Công ty An");
    await u.type(screen.getByLabelText("Họ tên"), "An");
    await u.type(screen.getByLabelText("Email"), "an@test.local");
    await u.type(screen.getByLabelText("Mật khẩu"), "password123");
    await u.click(screen.getByTestId("register-submit"));
    await waitFor(() =>
      expect(authApi.register).toHaveBeenCalledWith({ name: "An", email: "an@test.local", password: "password123", invite_token: null, tenant_name: "Công ty An" }),
    );
  });

  it("default_tenant → không hỏi tên tổ chức; bắt buộc xác thực (không token) → màn kiểm tra email", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ email_verification: "required" }));
    vi.mocked(authApi.register).mockResolvedValue({ ...loginResult(me({ email: "an@test.local", email_verified: false })), tokens: null, verification_sent: true });
    renderPage(<RegisterPage />, { path: "/register", route: "/register", user: null });
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Họ tên"), "An");
    expect(screen.queryByTestId("register-tenant")).toBeNull();
    await u.type(screen.getByLabelText("Email"), "an@test.local");
    await u.type(screen.getByLabelText("Mật khẩu"), "password123");
    await u.click(screen.getByTestId("register-submit"));
    expect((await screen.findByTestId("register-check-email")).textContent).toContain("an@test.local");
    expect(useAuthStore.getState().user).toBeNull();
  });
});

describe("InvitePage", () => {
  it("link hợp lệ → xem trước tổ chức + vai trò, đăng ký gửi kèm invite_token", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo());
    vi.mocked(tenantApi.preview).mockResolvedValue({ tenant_name: "Acme", role_name: "viewer", email: "b***@acme.io", expires_at: "2026-10-22T00:00:00Z" });
    vi.mocked(authApi.register).mockResolvedValue(loginResult());
    renderPage(<InvitePage />, { path: "/invite/:token", route: "/invite/tok-1", user: null });
    const preview = await screen.findByTestId("invite-preview");
    expect(preview.textContent).toContain("Bạn được mời vào Acme với vai trò viewer");
    expect(preview.textContent).toContain("b***@acme.io");
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Họ tên"), "Bình");
    await u.type(screen.getByLabelText("Email"), "binh@acme.io");
    await u.type(screen.getByLabelText("Mật khẩu"), "password123");
    await u.click(screen.getByTestId("register-submit"));
    await waitFor(() =>
      expect(authApi.register).toHaveBeenCalledWith({ name: "Bình", email: "binh@acme.io", password: "password123", invite_token: "tok-1", tenant_name: null }),
    );
    expect(await screen.findByTestId("where")).toBeTruthy();
  });

  it("link hết hạn → báo lỗi + link về đăng nhập, không có form", async () => {
    vi.mocked(tenantApi.preview).mockRejectedValue(expired());
    renderPage(<InvitePage />, { path: "/invite/:token", route: "/invite/old", user: null });
    expect(await screen.findByText("Link mời không hợp lệ hoặc đã hết hạn")).toBeTruthy();
    expect(screen.queryByTestId("register-submit")).toBeNull();
  });
});

describe("ForgotPasswordPage", () => {
  it("cần email hợp lệ; gửi xong luôn báo trung tính", async () => {
    vi.mocked(authApi.forgotPassword).mockResolvedValue({ ok: true });
    renderPage(<ForgotPasswordPage />, { path: "/forgot-password", route: "/forgot-password", user: null });
    const u = userEvent.setup();
    expect(screen.getByTestId("forgot-submit").hasAttribute("disabled")).toBe(true);
    await u.type(screen.getByTestId("forgot-email"), " an@test.local ");
    await u.click(screen.getByTestId("forgot-submit"));
    expect((await screen.findByTestId("forgot-sent")).textContent).toContain("Nếu email có tài khoản");
    expect(authApi.forgotPassword).toHaveBeenCalledWith("an@test.local");
  });

  it("lỗi mạng / rate limit → báo lỗi, vẫn ở form", async () => {
    vi.mocked(authApi.forgotPassword).mockRejectedValue(new ApiError({ message: "x", status: 429, code: 1007, correlationId: "c-2" }));
    renderPage(<ForgotPasswordPage />, { path: "/forgot-password", route: "/forgot-password", user: null });
    const u = userEvent.setup();
    await u.type(screen.getByTestId("forgot-email"), "an@test.local");
    await u.click(screen.getByTestId("forgot-submit"));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByTestId("forgot-sent")).toBeNull();
  });
});

describe("ResetPasswordPage", () => {
  it("không có token → khoá nút", () => {
    renderPage(<ResetPasswordPage />, { path: "/reset-password", route: "/reset-password", user: null });
    expect(screen.getByTestId("reset-submit").hasAttribute("disabled")).toBe(true);
  });

  it("mật khẩu ≥ 8 ký tự → đổi xong báo đăng nhập lại; token hết hạn → báo lỗi", async () => {
    vi.mocked(authApi.resetPassword).mockRejectedValueOnce(expired()).mockResolvedValueOnce({ ok: true });
    renderPage(<ResetPasswordPage />, { path: "/reset-password", route: "/reset-password?token=tk", user: null });
    const u = userEvent.setup();
    await u.type(screen.getByTestId("reset-password"), "1234567");
    expect(screen.getByTestId("reset-submit").hasAttribute("disabled")).toBe(true);
    await u.type(screen.getByTestId("reset-password"), "8");
    await u.click(screen.getByTestId("reset-submit"));
    expect((await screen.findByRole("alert")).textContent).toContain("Link không hợp lệ hoặc đã hết hạn");
    await u.click(screen.getByTestId("reset-submit"));
    expect(await screen.findByTestId("reset-done")).toBeTruthy();
    expect(authApi.resetPassword).toHaveBeenLastCalledWith("tk", "12345678");
  });
});

describe("VerifyEmailPage", () => {
  it("mở trang → xác thực một lần; đang đăng nhập → cờ email_verified bật ngay", async () => {
    vi.mocked(authApi.verifyEmail).mockResolvedValue({ ok: true });
    renderPage(<VerifyEmailPage />, { path: "/verify-email", route: "/verify-email?token=v1", user: me({ email_verified: false }) });
    expect(await screen.findByTestId("verify-done")).toBeTruthy();
    expect(authApi.verifyEmail).toHaveBeenCalledTimes(1);
    expect(authApi.verifyEmail).toHaveBeenCalledWith("v1");
    expect(useAuthStore.getState().user?.email_verified).toBe(true);
  });

  it("token hỏng → báo lỗi, link về đăng nhập khi chưa đăng nhập", async () => {
    vi.mocked(authApi.verifyEmail).mockRejectedValue(expired());
    renderPage(<VerifyEmailPage />, { path: "/verify-email", route: "/verify-email?token=bad", user: null });
    expect((await screen.findByRole("alert")).textContent).toContain("Link không hợp lệ");
    expect(screen.getByText("Về trang đăng nhập")).toBeTruthy();
  });
});

describe("VerifyBanner", () => {
  it("chưa xác thực + chế độ soft → hiện; gửi lại một lần", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ email_verification: "soft" }));
    vi.mocked(authApi.requestVerify).mockResolvedValue({ ok: true });
    renderPage(<VerifyBanner />, { user: me({ email_verified: false }) });
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("verify-banner-send"));
    expect(authApi.requestVerify).toHaveBeenCalledWith("u1@test.local");
    expect(toast.success).toHaveBeenCalled();
    expect(screen.getByTestId("verify-banner-send").hasAttribute("disabled")).toBe(true);
  });

  it("đã xác thực / chế độ off / superadmin → không hiện", async () => {
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo({ email_verification: "off" }));
    const view = renderPage(<VerifyBanner />, { user: me({ email_verified: false }) });
    await waitFor(() => expect(systemApi.publicInfo).toHaveBeenCalled());
    expect(screen.queryByTestId("verify-banner")).toBeNull();
    view.unmount();
    vi.mocked(systemApi.publicInfo).mockResolvedValue(publicInfo());
    renderPage(<VerifyBanner />, { user: me() });
    await waitFor(() => expect(systemApi.publicInfo).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("verify-banner")).toBeNull();
  });
});
