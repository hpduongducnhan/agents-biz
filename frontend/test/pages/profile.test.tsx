// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { getRefreshToken } from "@/lib/auth-tokens";
import { useAuthStore } from "@/lib/auth/store";
import { useLocaleStore } from "@/lib/i18n";
import ProfilePage from "@/pages/profile/ProfilePage";

import { me } from "../fixtures";
import { renderPage } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/auth/api", () => ({ authApi: { updateMe: vi.fn(), changePassword: vi.fn(), me: vi.fn(), logoutAll: vi.fn() } }));
const { authApi } = await import("@/features/auth/api");

const TOKENS = { access_token: "a-new", refresh_token: "r-new", token_type: "bearer", expires_in: 1800 };
const where = async () => (await screen.findByTestId("where")).textContent;
const open = (route: string, user = me()) => renderPage(<ProfilePage />, { path: "/profile", route, user });

async function fillPassword(current: string | null, next: string, confirm: string) {
  const u = userEvent.setup();
  if (current !== null) await u.type(screen.getByTestId("pw-current"), current);
  await u.type(screen.getByTestId("pw-new"), next);
  await u.type(screen.getByTestId("pw-confirm"), confirm);
  await u.click(screen.getByTestId("change-password"));
}

describe("ProfilePage — thông tin", () => {
  it("lưu tên, múi giờ, ngôn ngữ → cập nhật store + đổi ngôn ngữ ngay", async () => {
    vi.mocked(authApi.updateMe).mockResolvedValue(me({ name: "Tên Mới", locale: "en" }));
    open("/profile");
    const u = userEvent.setup();
    const name = await screen.findByTestId("profile-name");
    await u.clear(name);
    await u.type(name, "Tên Mới");
    await u.selectOptions(screen.getByTestId("profile-locale"), "en");
    await u.click(screen.getByTestId("profile-save"));
    await waitFor(() =>
      expect(authApi.updateMe).toHaveBeenCalledWith({ name: "Tên Mới", timezone: "Asia/Ho_Chi_Minh", locale: "en" }),
    );
    await waitFor(() => expect(useLocaleStore.getState().locale).toBe("en"));
    expect(useAuthStore.getState().user?.name).toBe("Tên Mới");
    expect(toast.success).toHaveBeenCalled();
    useLocaleStore.getState().setLocale("vi");
  });
});

describe("ProfilePage — mật khẩu", () => {
  it("nhập lại không khớp / quá ngắn → báo trong form, không gọi API", async () => {
    open("/profile?tab=password");
    await fillPassword("old-pass-1", "new-pass-12", "khac-han-1");
    expect((await screen.findByRole("alert")).textContent).toContain("Mật khẩu nhập lại không khớp");
    expect(authApi.changePassword).not.toHaveBeenCalled();
  });

  it("bị buộc đổi: cảnh báo + khoá tab khác; đổi xong dùng phiên mới rồi về /", async () => {
    vi.mocked(authApi.changePassword).mockResolvedValue(TOKENS);
    vi.mocked(authApi.me).mockResolvedValue(me({ must_change_password: false }));
    open("/profile", me({ must_change_password: true }));
    expect(await screen.findByTestId("force-change")).toBeTruthy();
    expect(screen.getByTestId("profile-tab-info").hasAttribute("disabled")).toBe(true);
    await fillPassword("old-pass-1", "new-pass-12", "new-pass-12");
    expect(await where()).toBe("/");
    expect(authApi.changePassword).toHaveBeenCalledWith({ current_password: "old-pass-1", new_password: "new-pass-12" });
    expect(getRefreshToken()).toBe("r-new");
    expect(useAuthStore.getState().user?.must_change_password).toBe(false);
  });

  it("mật khẩu hiện tại sai (2106) → thông điệp + Mã tra cứu", async () => {
    vi.mocked(authApi.changePassword).mockRejectedValue(new ApiError({ message: "x", status: 400, code: 2106, correlationId: "c-6" }));
    open("/profile?tab=password");
    await fillPassword("sai-roi-1", "new-pass-12", "new-pass-12");
    expect((await screen.findByRole("alert")).textContent).toContain("Mật khẩu hiện tại không đúng");
    expect(screen.getByTestId("error-cid").textContent).toBe("Mã tra cứu: c-6");
  });

  it("tài khoản chỉ đăng nhập Google (has_password=false): không hỏi mật khẩu cũ, gửi chuỗi rỗng", async () => {
    vi.mocked(authApi.changePassword).mockResolvedValue(TOKENS);
    vi.mocked(authApi.me).mockResolvedValue(me({ has_password: true }));
    open("/profile?tab=password", me({ has_password: false }));
    expect(screen.queryByTestId("pw-current")).toBeNull();
    await fillPassword(null, "new-pass-12", "new-pass-12");
    await waitFor(() => expect(authApi.changePassword).toHaveBeenCalledWith({ current_password: "", new_password: "new-pass-12" }));
  });
});

describe("ProfilePage — phiên đăng nhập", () => {
  it("đăng xuất mọi nơi: xác nhận → API → về /login", async () => {
    vi.mocked(authApi.logoutAll).mockResolvedValue(null);
    open("/profile?tab=sessions");
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("logout-all"));
    await u.click(await screen.findByRole("button", { name: "Xác nhận" }));
    expect(await where()).toBe("/login");
    expect(useAuthStore.getState().user).toBeNull();
  });
});

