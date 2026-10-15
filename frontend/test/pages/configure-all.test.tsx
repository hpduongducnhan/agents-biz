// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Credential } from "@/features/agent/api";
import { ApiError } from "@/lib/api/errors";
import { translate } from "@/lib/i18n";
import { AgentsTab } from "@/pages/studio/AgentsTab";

import { me } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/agent/api", () => {
  const fns = (...names: string[]) => Object.fromEntries(names.map((n) => [n, vi.fn()]));
  return { studioApi: fns("models", "agents", "configureAll"), credentialsApi: fns("list") };
});
const { studioApi, credentialsApi } = await import("@/features/agent/api");
const { toast } = await import("../sonner-mock");

const model = (id: string, provider_id: string, name: string) => ({
  id, model_id: name, name, provider_id, provider_name: provider_id === "p1" ? "Giả" : "Khác", status: "active", context_window: null,
  input_price_per_1m: "0", output_price_per_1m: "0", cache_read_price_per_1m: "0", cache_write_price_per_1m: "0",
}); // fmt: skip
const cred = (id: string, name: string, provider_id: string | null, status = "active"): Credential => ({
  id, name, kind: "api_key", provider_id, masked_hint: "fa…ey", weight: 1, status, disabled_reason: null, key_id: "k",
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
}); // fmt: skip
const firstArg = (fn: unknown) => (fn as ReturnType<typeof vi.fn>).mock.calls[0]?.[0];

beforeEach(() => {
  setDesktop(false);
  vi.mocked(studioApi.agents).mockResolvedValue([]);
  vi.mocked(studioApi.models).mockResolvedValue([model("m1", "p1", "fake-model"), model("m2", "p2", "other-model")]);
  vi.mocked(credentialsApi.list).mockResolvedValue({
    items: [cred("c1", "Key giả", "p1"), cred("c2", "Key khác", "p2"), cred("c3", "Key chung", null), cred("c4", "Key tắt", "p1", "disabled")],
    total: 4, limit: 100, offset: 0,
  }); // fmt: skip
});

const open = () => renderPage(<AgentsTab />, { path: "/studio", route: "/studio", user: me({ is_superadmin: true, permissions: [] }) });

describe("ConfigureAllDialog", () => {
  it("mở hộp thoại; nút lưu khoá tới khi chọn model + ít nhất một key", async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("agent-configure-all"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("dialog-submit").hasAttribute("disabled")).toBe(true);
    await u.selectOptions(within(dialog).getByTestId("configure-all-model"), "m1");
    expect(within(dialog).getByTestId("dialog-submit").hasAttribute("disabled")).toBe(true);
    await u.click(await within(dialog).findByLabelText(/Key giả/));
    expect(within(dialog).getByTestId("dialog-submit").hasAttribute("disabled")).toBe(false);
  });

  it("chỉ liệt kê key active cùng provider của model (+ key chung); đổi model → danh sách đổi", async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("agent-configure-all"));
    const dialog = await screen.findByRole("dialog");
    await u.selectOptions(within(dialog).getByTestId("configure-all-model"), "m1");
    expect(within(dialog).getByLabelText(/Key giả/)).toBeTruthy();
    expect(within(dialog).getByLabelText(/Key chung/)).toBeTruthy();
    expect(within(dialog).queryByLabelText(/Key khác/)).toBeNull();
    expect(within(dialog).queryByLabelText(/Key tắt/)).toBeNull();
    await u.selectOptions(within(dialog).getByTestId("configure-all-model"), "m2");
    expect(within(dialog).getByLabelText(/Key khác/)).toBeTruthy();
    expect(within(dialog).queryByLabelText(/Key giả/)).toBeNull();
  });

  it("lưu → studio.configure_all {model_id, credential_ids}, toast đã lưu, đóng hộp thoại", async () => {
    vi.mocked(studioApi.configureAll).mockResolvedValue({ agents: 7 });
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("agent-configure-all"));
    const dialog = await screen.findByRole("dialog");
    await u.selectOptions(within(dialog).getByTestId("configure-all-model"), "m1");
    await u.click(await within(dialog).findByLabelText(/Key giả/));
    await u.click(within(dialog).getByLabelText(/Key chung/));
    await u.click(within(dialog).getByTestId("dialog-submit"));
    await waitFor(() => expect(studioApi.configureAll).toHaveBeenCalled());
    expect(firstArg(studioApi.configureAll)).toEqual({ model_id: "m1", credential_ids: ["c1", "c3"] });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(toast.success).toHaveBeenCalledWith("Đã lưu");
  });

  it("key khác provider (6020) → toast lỗi dịch được, hộp thoại giữ nguyên", async () => {
    vi.mocked(studioApi.configureAll).mockRejectedValue(new ApiError({ message: "mismatch", status: 422, code: 6020 }));
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("agent-configure-all"));
    const dialog = await screen.findByRole("dialog");
    await u.selectOptions(within(dialog).getByTestId("configure-all-model"), "m1");
    await u.click(await within(dialog).findByLabelText(/Key giả/));
    await u.click(within(dialog).getByTestId("dialog-submit"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).toBe(translate("err.6020"));
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});
