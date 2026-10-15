// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatGuardPage from "@/pages/sa/ChatGuardPage";

import { adminUser, me, page, settingsOut } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/system/api", () => ({ systemApi: { getSettings: vi.fn(), updateSettings: vi.fn() } }));
vi.mock("@/features/agent/guardApi", () => ({ guardApi: { listBlocks: vi.fn(), block: vi.fn(), unblock: vi.fn(), chatLimits: vi.fn() } }));
vi.mock("@/features/admin/api", () => ({ adminApi: { listUsers: vi.fn() } }));
const { systemApi } = await import("@/features/system/api");
const { guardApi } = await import("@/features/agent/guardApi");
const { adminApi } = await import("@/features/admin/api");

const SUPER = me({ is_superadmin: true });
const block = (over: Record<string, unknown> = {}) => ({
  id: "b1",
  user: { id: "u2", email: "u2@test.local", name: "Người Dùng Hai" },
  until: "2026-10-14T12:00:00Z",
  reason: "Chạm hạn mức chat 5 lần",
  source: "auto",
  created_by: null,
  created_at: "2026-10-14T11:00:00Z",
  lifted_at: null,
  lifted_by: null,
  active: true,
  ...over,
});
const blocks = (...items: ReturnType<typeof block>[]) => ({ items, total: items.length, limit: 50, offset: 0 });
const open = () => renderPage(<ChatGuardPage />, { path: "/sa/chat-guard", route: "/sa/chat-guard", user: SUPER });
const saveBtn = () => screen.getByTestId("guard-save") as HTMLButtonElement;

beforeEach(() => {
  setDesktop(false);
  vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut({ defaults_applied: ["chat_per_minute"] }));
  vi.mocked(systemApi.updateSettings).mockResolvedValue(settingsOut());
  vi.mocked(guardApi.listBlocks).mockImplementation(async (q) => (q.active_only ? blocks(block()) : blocks(block(), block({ id: "b0", lifted_at: "2026-10-14T11:30:00Z", active: false, source: "manual", created_by: "Root" }))));
  vi.mocked(guardApi.unblock).mockResolvedValue(block({ active: false }) as never);
  vi.mocked(guardApi.block).mockResolvedValue(block({ source: "manual" }) as never);
  vi.mocked(adminApi.listUsers).mockResolvedValue(page([adminUser(), adminUser({ id: "u3", email: "u3@test.local", name: "Ba" })]) as never);
});

describe("ChatGuardPage", () => {
  it("hiện giá trị từ cài đặt, badge mặc định và câu mô tả luật", async () => {
    open();
    expect(((await screen.findByTestId("guard-field-chat_per_minute")) as HTMLInputElement).value).toBe("10");
    expect((screen.getByTestId("guard-field-chat_per_hour") as HTMLInputElement).value).toBe("100");
    expect((screen.getByTestId("guard-field-chat_per_day") as HTMLInputElement).value).toBe("400");
    expect(screen.getByTestId("guard-default-chat_per_minute")).toBeTruthy();
    expect(screen.queryByTestId("guard-default-chat_per_hour")).toBeNull();
    expect(screen.getByTestId("guard-rule").textContent).toContain("5 lần trong 10 phút → chặn 30 phút");
    expect(saveBtn().disabled).toBe(true);
  });

  it("chỉ gửi khoá đã đổi", async () => {
    open();
    const u = userEvent.setup();
    const f = await screen.findByTestId("guard-field-chat_per_minute");
    await u.clear(f);
    await u.type(f, "3");
    await u.click(screen.getByTestId("guard-autoblock"));
    await u.click(saveBtn());
    await waitFor(() => expect(systemApi.updateSettings).toHaveBeenCalledWith({ chat_per_minute: 3, chat_autoblock: false }));
  });

  it("câu luật đổi theo ô nhập; tắt tự chặn thì hiện câu 'đang tắt'", async () => {
    open();
    const u = userEvent.setup();
    const f = await screen.findByTestId("guard-field-chat_autoblock_strikes");
    await u.clear(f);
    await u.type(f, "2");
    expect(screen.getByTestId("guard-rule").textContent).toContain("2 lần");
    await u.click(screen.getByTestId("guard-autoblock"));
    expect(screen.getByTestId("guard-rule").textContent).toContain("Đang tắt");
  });

  it("giá trị không hợp lệ khoá nút lưu", async () => {
    open();
    const u = userEvent.setup();
    const f = await screen.findByTestId("guard-field-chat_autoblock_strikes");
    await u.clear(f);
    await u.type(f, "0"); // tối thiểu 1
    expect(saveBtn().disabled).toBe(true);
    await u.clear(f);
    await u.type(f, "abc");
    expect(saveBtn().disabled).toBe(true);
    await u.clear(f);
    await u.type(f, "7");
    expect(saveBtn().disabled).toBe(false);
    const g = screen.getByTestId("guard-field-chat_per_day");
    await u.clear(g);
    expect(saveBtn().disabled).toBe(true);
    expect(systemApi.updateSettings).not.toHaveBeenCalled();
  });
});

describe("ChatBlocksPanel", () => {
  it("liệt kê đang bị chặn (thẻ trên điện thoại) và mở chặn gọi studio.unblock_chat", async () => {
    open();
    const row = await screen.findByTestId("guard-block-b1");
    expect(row.tagName).toBe("LI");
    expect(within(row).getByText("Người Dùng Hai")).toBeTruthy();
    expect(guardApi.listBlocks).toHaveBeenCalledWith(expect.objectContaining({ active_only: true }));
    await userEvent.setup().click(screen.getByTestId("guard-unblock-b1"));
    await waitFor(() => expect(guardApi.unblock).toHaveBeenCalledWith("b1"));
  });

  it("desktop: dạng bảng, có cột nguồn", async () => {
    setDesktop(true);
    open();
    const row = await screen.findByTestId("guard-block-b1");
    expect(row.closest("table")).not.toBeNull();
    expect(within(row).getByText("Tự động")).toBeTruthy();
  });

  it("tab lịch sử: gọi active_only=false, mục đã mở chặn không có nút mở", async () => {
    open();
    const u = userEvent.setup();
    await screen.findByTestId("guard-block-b1");
    await u.click(screen.getByTestId("guard-tab-history"));
    const lifted = await screen.findByTestId("guard-block-b0");
    expect(within(lifted).queryByTestId("guard-unblock-b0")).toBeNull();
    expect(guardApi.listBlocks).toHaveBeenCalledWith(expect.objectContaining({ active_only: false }));
  });

  it("không có ai bị chặn → trạng thái rỗng", async () => {
    vi.mocked(guardApi.listBlocks).mockResolvedValue(blocks());
    open();
    expect(await screen.findByText("Không có ai đang bị chặn")).toBeTruthy();
  });
});

describe("BlockChatDialog", () => {
  const openDialog = async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("guard-block-user"));
    await u.click(await screen.findByTestId("guard-pick-u2"));
    return u;
  };

  it("chọn user + 'tới khi mở' → minutes null; lý do bắt buộc", async () => {
    const u = await openDialog();
    const submit = screen.getByTestId("dialog-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true); // chưa có lý do
    await u.selectOptions(screen.getByTestId("guard-duration"), "open");
    await u.type(screen.getByTestId("guard-reason"), "   ");
    expect(submit.disabled).toBe(true); // chỉ có khoảng trắng
    await u.type(screen.getByTestId("guard-reason"), "Spam thử");
    expect(submit.disabled).toBe(false);
    await u.click(submit);
    await waitFor(() => expect(guardApi.block).toHaveBeenCalledWith({ user_id: "u2", minutes: null, reason: "Spam thử" }));
  });

  it("mặc định 1 giờ = 60 phút; cần chọn user", async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("guard-block-user"));
    await u.type(await screen.findByTestId("guard-reason"), "lý do");
    expect((screen.getByTestId("dialog-submit") as HTMLButtonElement).disabled).toBe(true); // chưa chọn user
    await u.click(await screen.findByTestId("guard-pick-u3"));
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() => expect(guardApi.block).toHaveBeenCalledWith({ user_id: "u3", minutes: 60, reason: "lý do" }));
  });
});
