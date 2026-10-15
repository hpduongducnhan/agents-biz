// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SettingsPage from "@/pages/sa/SettingsPage";

import { me, settingsOut } from "../fixtures";
import { renderPage } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/system/api", () => ({ systemApi: { getSettings: vi.fn(), updateSettings: vi.fn() } }));
const { systemApi } = await import("@/features/system/api");

const open = () => renderPage(<SettingsPage />, { path: "/sa/settings", route: "/sa/settings", user: me({ is_superadmin: true }) });

describe("SettingsPage (superadmin)", () => {
  it("đổi chế độ đăng ký → chỉ gửi trường đổi", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut());
    vi.mocked(systemApi.updateSettings).mockResolvedValue(settingsOut({ signup_mode: "invite_only" }));
    open();
    const u = userEvent.setup();
    await u.selectOptions(await screen.findByTestId("settings-signup-mode"), "invite_only");
    await u.click(screen.getByTestId("settings-save"));
    await waitFor(() => expect(systemApi.updateSettings).toHaveBeenCalledWith({ signup_mode: "invite_only" }));
  });

  it("tham số số: hợp lệ → gửi số; để trống → báo lỗi + khoá nút lưu", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut());
    vi.mocked(systemApi.updateSettings).mockResolvedValue(settingsOut({ event_log_ttl_days: 30 }));
    open();
    const u = userEvent.setup();
    const field = await screen.findByTestId("settings-field-event_log_ttl_days");
    await u.clear(field);
    expect(screen.getByText(/Nhập số nguyên/)).toBeTruthy();
    expect(screen.getByTestId("settings-save").hasAttribute("disabled")).toBe(true);
    await u.type(field, "30");
    await u.click(screen.getByTestId("settings-save"));
    await waitFor(() => expect(systemApi.updateSettings).toHaveBeenCalledWith({ event_log_ttl_days: 30 }));
  });

  it("Google chưa cấu hình → công tắc khoá + gợi ý; khoá đang dùng mặc định có badge (R11)", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut({ google_configured: false, google_enabled: false }));
    open();
    expect((await screen.findByTestId("settings-google")).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/Chưa cấu hình GOOGLE_CLIENT_ID/)).toBeTruthy();
    expect(screen.getByTestId("settings-default-event_log_ttl_days")).toBeTruthy();
    expect(screen.queryByTestId("settings-default-span_ttl_days")).toBeNull();
  });
});

describe("SettingsPage — cài đặt chat đã chuyển", () => {
  it("không còn ô / công tắc chat; có link tới /sa/ai-settings", async () => {
    vi.mocked(systemApi.getSettings).mockResolvedValue(settingsOut());
    open();
    const link = await screen.findByTestId("settings-ai-link");
    expect(link.getAttribute("href")).toBe("/sa/ai-settings");
    for (const k of ["chat_session_idle_min", "chat_history_limit", "chat_stream_flush_ms"]) expect(screen.queryByTestId(`settings-field-${k}`)).toBeNull();
    expect(screen.queryByTestId("settings-chat-tools")).toBeNull();
    expect(screen.queryByTestId("settings-chat-stream")).toBeNull();
  });
});
