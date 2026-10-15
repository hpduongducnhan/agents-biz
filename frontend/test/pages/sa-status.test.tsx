// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { StatusResult } from "@/lib/status";
import { StatusPage } from "@/pages/sa/StatusPage";

import { me, statusOut } from "../fixtures";
import { renderPage } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/system/api", () => ({ systemApi: { status: vi.fn() } }));
vi.mock("@/features/notifications/api", () => ({ notificationsApi: { sendTest: vi.fn() } }));
const { systemApi } = await import("@/features/system/api");
const { notificationsApi } = await import("@/features/notifications/api");

const RESULT: StatusResult = {
  version: "abc123",
  services: [
    { name: "api", label: "API", light: "up", detail: "HTTP 200" },
    { name: "realtime", label: "Realtime", light: "down", detail: "không phản hồi" },
  ],
};
const SA = me({ is_superadmin: true, permissions: [] });
const open = (check: () => Promise<StatusResult>) => renderPage(<StatusPage check={check} />, { path: "/sa/status", route: "/sa/status", user: SA });

beforeEach(() => vi.mocked(systemApi.status).mockResolvedValue(statusOut()));

describe("StatusPage (superadmin)", () => {
  it("đèn từng thành phần + phiên bản; chi tiết system.status bằng JsonView + badge Mongo", async () => {
    open(async () => RESULT);
    expect(await screen.findByText("Realtime")).toBeTruthy();
    expect(screen.getByTestId("light-api").getAttribute("data-light")).toBe("up");
    expect(screen.getByTestId("light-realtime").getAttribute("data-light")).toBe("down");
    expect(screen.getByText("Phiên bản abc123")).toBeTruthy();
    expect((await screen.findByTestId("status-mongo")).textContent).toBe("Mongo đang bật");
    expect(screen.getByTestId("json-view")).toBeTruthy();
  });

  it("kiểm trạng thái lỗi → vẫn hiện trang với thông báo (không trắng trang)", async () => {
    open(async () => Promise.reject(new Error("x")));
    expect((await screen.findByRole("alert")).textContent).toBe("Không lấy được trạng thái");
  });

  it("gửi thông báo thử tới user theo email", async () => {
    vi.mocked(notificationsApi.sendTest).mockResolvedValue({ notification_id: "n9" });
    open(async () => RESULT);
    const u = userEvent.setup();
    await u.type(await screen.findByTestId("send-test-email"), "u1@test.local");
    await u.type(screen.getByTestId("send-test-title"), "Xin chào");
    await u.click(screen.getByTestId("send-test-submit"));
    await waitFor(() => expect(notificationsApi.sendTest).toHaveBeenCalledWith({ email: "u1@test.local", title: "Xin chào", body: "" }));
    expect(toast.success).toHaveBeenCalledWith("Đã gửi tới u1@test.local");
  });

  it("email không có user (1001) → lỗi trong thẻ kèm Mã tra cứu", async () => {
    vi.mocked(notificationsApi.sendTest).mockRejectedValue(new ApiError({ message: "Không có user với email này", status: 404, code: 1001, correlationId: "c-1" }));
    open(async () => RESULT);
    const u = userEvent.setup();
    await u.type(await screen.findByTestId("send-test-email"), "khong-co@test.local");
    await u.type(screen.getByTestId("send-test-title"), "Thử");
    await u.click(screen.getByTestId("send-test-submit"));
    const alert = await screen.findByTestId("error-cid");
    expect(alert.textContent).toBe("Mã tra cứu: c-1");
    expect(screen.getByText("Không có user với email này")).toBeTruthy();
  });
});
