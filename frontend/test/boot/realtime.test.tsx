// @vitest-environment jsdom
import { renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCoreRealtime } from "@/boot/realtime";
import { notifTitle } from "@/features/notifications/notif";
import { useAuthStore } from "@/lib/auth/store";
import { registerDictionary, translate } from "@/lib/i18n";
import { queryClient } from "@/lib/query-client";
import { type RealtimeHandler, socketManager } from "@/lib/realtime/socket";

import { me } from "../fixtures";
import { Where } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/auth/api", () => ({ authApi: { me: vi.fn() } }));
const { authApi } = await import("@/features/auth/api");

const handlers = new Map<string, RealtimeHandler>();

function mount() {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={["/admin/users"]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              {children}
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
  return renderHook(() => useCoreRealtime(), { wrapper });
}

beforeEach(() => {
  handlers.clear();
  vi.spyOn(socketManager, "on").mockImplementation((event, h) => (handlers.set(event, h), () => handlers.delete(event)));
  vi.spyOn(socketManager, "connect").mockImplementation(() => undefined);
  vi.spyOn(socketManager, "disconnect").mockImplementation(() => undefined);
  vi.spyOn(socketManager, "refreshAuth").mockResolvedValue(undefined);
  vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);
  useAuthStore.setState({ user: me({ permissions: ["user.view"] }), isAuthenticated: true });
  vi.mocked(authApi.me).mockResolvedValue(me({ id: "u1", permissions: [] }));
});

const fire = (event: string, data?: unknown, meta?: unknown) => handlers.get(event)?.(data, meta as never);
const invalidated = () => vi.mocked(queryClient.invalidateQueries).mock.calls.map((c) => (c[0] as { queryKey: unknown[] }).queryKey);

describe("useCoreRealtime", () => {
  it("đã đăng nhập → nối socket + đăng ký handler; unmount thì gỡ", () => {
    const view = mount();
    expect(socketManager.connect).toHaveBeenCalled();
    expect([...handlers.keys()].sort()).toEqual(
      ["auth:expired", "core:account_disabled", "core:notification", "core:rbac_updated", "data:changed", "sys:error"].sort(),
    );
    view.unmount();
    expect(handlers.size).toBe(0);
  });

  it("data:changed → làm mới đúng các key theo tiền tố", () => {
    mount();
    fire("data:changed", { keys: ["admin.users", "notifications.unread"] });
    expect(invalidated()).toEqual([["admin", "users"], ["notifications", "unread"]]);
  });

  it("core:rbac_updated → refresh token, tải lại me (mất quyền ngay), báo", async () => {
    mount();
    fire("core:rbac_updated", {});
    await waitFor(() => expect(toast.info).toHaveBeenCalledWith("Quyền của bạn vừa thay đổi"));
    expect(socketManager.refreshAuth).toHaveBeenCalled();
    expect(useAuthStore.getState().user?.permissions).toEqual([]);
  });

  it("core:notification → toast tiêu đề + nội dung, làm mới chuông", () => {
    mount();
    fire("core:notification", { id: "n9", kind: "test", title: "Có phiếu mới", body: "Từ An", params: {} });
    expect(toast).toHaveBeenCalledWith("Có phiếu mới", { description: "Từ An" });
    expect(invalidated()).toContainEqual(["notifications"]);
  });

  it("core:account_disabled → đăng xuất, về /login?reason=disabled kèm thông báo", async () => {
    mount();
    fire("core:account_disabled", {});
    expect(toast.error).toHaveBeenCalledWith("Tài khoản của bạn đã bị khoá");
    expect(useAuthStore.getState().user).toBeNull();
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/login?reason=disabled"));
  });

  it("auth:expired → làm mới token socket; sys:error → toast có Mã tra cứu", () => {
    mount();
    fire("auth:expired");
    expect(socketManager.refreshAuth).toHaveBeenCalled();
    fire("sys:error", { code: 1005 }, { cid: "c-9" });
    expect(toast.error).toHaveBeenCalledWith("Yêu cầu realtime bị từ chối (mã 1005)", { description: "Mã tra cứu: c-9" });
  });
});

describe("notifTitle", () => {
  it("có key notif.kind.<kind> thì dịch theo tham số; không thì dùng tiêu đề BE", () => {
    registerDictionary("vi", { "notif.kind.demo": "Nhóm {group} có hoạt động mới" });
    expect(notifTitle(translate, { kind: "demo", title: "x", params: { group: "Nhà mẫu" } })).toBe("Nhóm Nhà mẫu có hoạt động mới");
    expect(notifTitle(translate, { kind: "khong_co", title: "Tiêu đề BE", params: null })).toBe("Tiêu đề BE");
  });
});
