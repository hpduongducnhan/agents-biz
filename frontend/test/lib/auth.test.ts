// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { getAccessToken, getRefreshToken } from "@/lib/auth-tokens";
import { hasPermission, PERMS } from "@/lib/auth/permissions";
import { useAuthStore } from "@/lib/auth/store";
import { useLocaleStore } from "@/lib/i18n";
import { queryClient } from "@/lib/query-client";
import { socketManager } from "@/lib/realtime/socket";

import { me } from "../fixtures";

const tokens = { access_token: "a2", refresh_token: "r2" };

afterEach(() => {
  vi.restoreAllMocks();
  useLocaleStore.getState().setLocale("vi");
});

describe("auth store", () => {
  it("login: lưu token, bắt tay lại socket bằng token mới, áp ngôn ngữ của user", () => {
    const calls: string[] = [];
    vi.spyOn(socketManager, "disconnect").mockImplementation(() => void calls.push("disconnect"));
    vi.spyOn(socketManager, "connect").mockImplementation(() => void calls.push(`connect:${getAccessToken()}`));
    useAuthStore.getState().login(tokens, me({ locale: "en" }));
    expect(calls).toEqual(["disconnect", "connect:a2"]);
    expect(getRefreshToken()).toBe("r2");
    expect(useAuthStore.getState()).toMatchObject({ isAuthenticated: true, user: { id: "u1" } });
    expect(useLocaleStore.getState().locale).toBe("en");
  });

  it("logout: xoá token, xoá cache, ngắt socket", () => {
    const clear = vi.spyOn(queryClient, "clear");
    const disconnect = vi.spyOn(socketManager, "disconnect").mockImplementation(() => undefined);
    vi.spyOn(socketManager, "connect").mockImplementation(() => undefined);
    useAuthStore.getState().login(tokens, me());
    useAuthStore.getState().logout();
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
    expect(useAuthStore.getState()).toMatchObject({ isAuthenticated: false, user: null });
    expect(clear).toHaveBeenCalled();
    expect(disconnect).toHaveBeenCalled();
  });

  it("setUser: cập nhật user + ngôn ngữ, không đụng token", () => {
    useAuthStore.getState().setUser(me({ name: "Mới", locale: "en" }));
    expect(useAuthStore.getState().user?.name).toBe("Mới");
    expect(useLocaleStore.getState().locale).toBe("en");
  });
});

describe("hasPermission", () => {
  it("superadmin qua mọi quyền; user cần đúng quyền; mảng = một trong; chưa đăng nhập = false", () => {
    const admin = me({ permissions: [PERMS.USER_VIEW, PERMS.USER_MANAGE] });
    expect(hasPermission(admin, PERMS.USER_VIEW)).toBe(true);
    expect(hasPermission(admin, PERMS.TENANT_INVITE)).toBe(false);
    expect(hasPermission(admin, [PERMS.TENANT_INVITE, PERMS.USER_MANAGE])).toBe(true);
    expect(hasPermission(me({ is_superadmin: true, permissions: [] }), PERMS.TENANT_INVITE)).toBe(true);
    expect(hasPermission(me(), undefined)).toBe(true);
    expect(hasPermission(null, undefined)).toBe(false);
    expect(hasPermission(null, PERMS.USER_VIEW)).toBe(false);
  });
});
