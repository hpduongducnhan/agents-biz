// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationsPage from "@/pages/notifications/NotificationsPage";
import { PushCard } from "@/pages/notifications/PushCard";
import { useUiStore } from "@/stores/ui.store";

import { renderPage } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/push/api", () => ({ pushApi: { config: vi.fn() } }));
vi.mock("@/features/notifications/api", () => ({
  notificationsApi: { list: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 }), markAllRead: vi.fn() },
  markReadFast: vi.fn(),
}));
vi.mock("@/lib/push", () => ({ pushState: vi.fn(), enablePush: vi.fn(), disablePush: vi.fn() }));
const { pushApi } = await import("@/features/push/api");
const { pushState, enablePush, disablePush } = await import("@/lib/push");
const { toast } = await import("../sonner-mock");

const KEY = "BKEY";
const config = (over: Partial<{ enabled: boolean; public_key: string | null }> = {}) =>
  vi.mocked(pushApi.config).mockResolvedValue({ enabled: true, public_key: KEY, ...over });

beforeEach(() => {
  vi.clearAllMocks();
  config();
  useUiStore.setState({ installGuideOpen: false });
});

describe("PushCard", () => {
  it("máy chủ chưa bật → ẩn thẻ", async () => {
    config({ enabled: false, public_key: null });
    vi.mocked(pushState).mockResolvedValue("off");
    const { container } = renderPage(<PushCard />);
    await waitFor(() => expect(pushApi.config).toHaveBeenCalled());
    await waitFor(() => expect(pushState).toHaveBeenCalled());
    expect(screen.queryByTestId("push-card")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("enabled nhưng thiếu khoá → ẩn", async () => {
    config({ public_key: null });
    vi.mocked(pushState).mockResolvedValue("off");
    renderPage(<PushCard />);
    await waitFor(() => expect(pushState).toHaveBeenCalled());
    expect(screen.queryByTestId("push-card")).toBeNull();
  });

  it("off: có nút Bật; bấm → enablePush(khoá) → on + toast thành công, hiện nút Tắt", async () => {
    vi.mocked(pushState).mockResolvedValue("off");
    vi.mocked(enablePush).mockResolvedValue("on");
    renderPage(<PushCard />);
    const card = await screen.findByTestId("push-card");
    expect(card.getAttribute("data-state")).toBe("off");
    await userEvent.setup().click(screen.getByTestId("push-enable"));
    await waitFor(() => expect(enablePush).toHaveBeenCalledWith(KEY));
    await screen.findByTestId("push-disable");
    expect(screen.getByTestId("push-card").getAttribute("data-state")).toBe("on");
    expect(screen.queryByTestId("push-enable")).toBeNull();
    expect(toast.success).toHaveBeenCalledWith("Đã bật thông báo trên máy này");
  });

  it("bật nhưng bị từ chối → state denied, không có nút, không toast", async () => {
    vi.mocked(pushState).mockResolvedValue("off");
    vi.mocked(enablePush).mockResolvedValue("denied");
    renderPage(<PushCard />);
    await userEvent.setup().click(await screen.findByTestId("push-enable"));
    await waitFor(() => expect(screen.getByTestId("push-card").getAttribute("data-state")).toBe("denied"));
    expect(screen.queryByTestId("push-enable")).toBeNull();
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getByText(/đang chặn thông báo/)).toBeTruthy();
  });

  it("on: bấm Tắt → disablePush, đọc lại trạng thái, toast, quay về off", async () => {
    vi.mocked(pushState).mockResolvedValueOnce("on").mockResolvedValue("off");
    vi.mocked(disablePush).mockResolvedValue(undefined);
    renderPage(<PushCard />);
    await userEvent.setup().click(await screen.findByTestId("push-disable"));
    await waitFor(() => expect(disablePush).toHaveBeenCalledOnce());
    await screen.findByTestId("push-enable");
    expect(toast.success).toHaveBeenCalledWith("Đã tắt thông báo trên máy này");
  });

  it("enablePush ném lỗi → toast lỗi, thẻ vẫn ở off, nút dùng lại được", async () => {
    vi.mocked(pushState).mockResolvedValue("off");
    vi.mocked(enablePush).mockRejectedValue(new Error("boom"));
    renderPage(<PushCard />);
    await userEvent.setup().click(await screen.findByTestId("push-enable"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect((screen.getByTestId("push-enable") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByTestId("push-card").getAttribute("data-state")).toBe("off");
  });

  it("needs-install: nút push-install mở hướng dẫn cài app, không có nút Bật", async () => {
    vi.mocked(pushState).mockResolvedValue("needs-install");
    renderPage(<PushCard />);
    await userEvent.setup().click(await screen.findByTestId("push-install"));
    expect(useUiStore.getState().installGuideOpen).toBe(true);
    expect(screen.queryByTestId("push-enable")).toBeNull();
  });

  it("unsupported: chỉ có chữ giải thích, không nút", async () => {
    vi.mocked(pushState).mockResolvedValue("unsupported");
    renderPage(<PushCard />);
    await screen.findByTestId("push-card");
    expect(screen.getByText("Trình duyệt này không hỗ trợ thông báo đẩy.")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("NotificationsPage", () => {
  it("hiện thẻ thông báo đẩy ở đầu trang", async () => {
    vi.mocked(pushState).mockResolvedValue("off");
    renderPage(<NotificationsPage />, { path: "/notifications", route: "/notifications" });
    expect(await screen.findByTestId("push-card")).toBeTruthy();
  });
});
