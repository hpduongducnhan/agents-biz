// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AiSettingsPage from "@/pages/sa/AiSettingsPage";

import { me, settingsOut } from "../fixtures";
import { renderPage } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/system/api", () => ({ systemApi: { getSettings: vi.fn(), updateSettings: vi.fn() } }));
const { systemApi } = await import("@/features/system/api");

const open = () => renderPage(<AiSettingsPage />, { path: "/sa/ai-settings", route: "/sa/ai-settings", user: me({ is_superadmin: true }) });
const flush = () => screen.findByTestId("settings-field-chat_stream_flush_ms") as Promise<HTMLInputElement>;

describe("AiSettingsPage", () => {
  it("hiện hai thẻ: Trợ lý chat (3 khoá) + Trả lời dạng stream", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut());
    open();
    await flush();
    for (const id of ["settings-field-chat_session_idle_min", "settings-field-chat_history_limit", "settings-chat-tools", "settings-chat-stream"])
      expect(screen.getByTestId(id)).toBeTruthy();
    expect(screen.getByText("Trả lời dạng stream")).toBeTruthy();
    expect(screen.getByTestId("settings-save").hasAttribute("disabled")).toBe(true);
  });

  it("tắt stream → ô flush bị khoá; bật lại → mở", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut());
    open();
    const field = await flush();
    expect(field.disabled).toBe(false);
    const u = userEvent.setup();
    await u.click(screen.getByTestId("settings-chat-stream"));
    expect(field.disabled).toBe(true);
    await u.click(screen.getByTestId("settings-chat-stream"));
    expect(field.disabled).toBe(false);
  });

  it("flush = 10 (ngoài 20–1000) → báo lỗi + khoá nút Lưu; 1001 cũng vậy; 20 hợp lệ", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut());
    open();
    const field = await flush();
    const u = userEvent.setup();
    for (const bad of ["10", "1001", ""]) {
      await u.clear(field);
      if (bad) await u.type(field, bad);
      expect(screen.getByText("Nhập số nguyên từ 20 đến 1000")).toBeTruthy();
      expect(screen.getByTestId("settings-save").hasAttribute("disabled")).toBe(true);
    }
    await u.type(field, "20");
    expect(screen.queryByText("Nhập số nguyên từ 20 đến 1000")).toBeNull();
    expect(screen.getByTestId("settings-save").hasAttribute("disabled")).toBe(false);
  });

  it("lưu chỉ gửi các trường đã đổi (stream, flush, khoá chat)", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut());
    vi.mocked(systemApi.updateSettings).mockResolvedValue(settingsOut({ chat_stream: false }));
    open();
    const flushField = await flush();
    const u = userEvent.setup();
    await u.clear(flushField);
    await u.type(flushField, "200");
    await u.click(screen.getByTestId("settings-chat-stream"));
    const idle = screen.getByTestId("settings-field-chat_session_idle_min");
    await u.clear(idle);
    await u.type(idle, "45");
    await u.click(screen.getByTestId("settings-chat-tools"));
    await u.click(screen.getByTestId("settings-save"));
    await waitFor(() =>
      expect(systemApi.updateSettings).toHaveBeenCalledWith({
        chat_stream: false,
        chat_stream_flush_ms: 200,
        chat_session_idle_min: 45,
        chat_history_tools: false,
      }),
    );
  });

  it("nhãn Mặc định chỉ ở khoá nằm trong defaults_applied (R11)", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut({ defaults_applied: ["chat_stream", "chat_stream_flush_ms", "chat_history_limit"] }));
    open();
    await flush();
    for (const k of ["chat_stream", "chat_stream_flush_ms", "chat_history_limit"]) expect(screen.getByTestId(`settings-default-${k}`)).toBeTruthy();
    expect(screen.queryByTestId("settings-default-chat_session_idle_min")).toBeNull();
    expect(screen.queryByTestId("settings-default-chat_history_tools")).toBeNull();
  });
});
