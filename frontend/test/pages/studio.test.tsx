// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Credential, StudioAgent } from "@/features/agent/api";
import { RequireSuperadmin } from "@/guards/guards";
import { ApiError } from "@/lib/api/errors";
import { translate } from "@/lib/i18n";
import StudioPage from "@/pages/studio/StudioPage";

import { me } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/agent/api", () => {
  const fns = (...names: string[]) => Object.fromEntries(names.map((n) => [n, vi.fn()]));
  return {
    studioApi: fns("providers", "models", "agents", "agent", "setKeys", "setLimits", "setUserLimit", "setToolsets", "setOverride", "catalog", "hooks", "saveHook", "deleteHook", "testHook", "saveAgent", "persona", "savePersona", "saveProvider", "deleteProvider", "testProvider", "saveModel", "deleteModel", "routes", "saveRoute", "deleteRoute"),
    credentialsApi: fns("list", "create", "update", "remove"),
    agentApi: fns("agents"),
    traceApi: fns("list"),
  };
});
const { studioApi, credentialsApi } = await import("@/features/agent/api");
const { toast } = await import("../sonner-mock");

const SA = me({ is_superadmin: true, permissions: [] });
const SECRET = "sk-SUPER-SECRET-VALUE-1234567890";

const cred = (over: Partial<Credential> = {}): Credential => ({
  id: "c1", name: "Key chính", kind: "api_key", provider_id: "p1", masked_hint: "sk-…7890", weight: 1, status: "active", disabled_reason: null, key_id: "k1",
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", ...over,
}); // fmt: skip
const agent = (over: Partial<StudioAgent> = {}): StudioAgent => ({
  id: "ag1", slug: "assistant", name: "Trợ lý", kind: "chat", description: "", instructions: "", persona_shared: true, starters: [], model_id: "m1", model_name: "gpt-x",
  params_override: {}, recursion_limit: 25, timeout_sec: 90, key_strategy: "round_robin", key_cooldown_sec: 300, visible_to: "all", visible_roles: [],
  is_active: true, keys: [], limits: { per_minute: null, per_hour: null, per_day: null, tokens_per_day: null }, toolsets: ["ledger"], overrides: [], hooks_count: 0, warnings: [],
  ...over,
}); // fmt: skip
const ops = [
  { name: "wallet_list", title: "Liệt kê ví", description: "", effect: "read", default_policy: "auto" },
  { name: "wallet_record", title: "Ghi giao dịch", description: "", effect: "write", default_policy: "confirm" },
];

/** TanStack v5 truyền thêm context vào mutationFn → chỉ so đối số đầu. */
const firstArg = (fn: unknown) => (fn as ReturnType<typeof vi.fn>).mock.calls[0]?.[0];

const open = (route: string, user = SA) => renderPage(<StudioPage />, { path: "/studio", route, user });

beforeEach(() => {
  setDesktop(false);
  vi.mocked(studioApi.providers).mockResolvedValue([{ id: "p1", name: "OpenAI", kind: "openai", base_url: null, extra_headers: {}, default_params: {}, status: "active", models_count: 1 }]);
  vi.mocked(studioApi.models).mockResolvedValue([]);
  vi.mocked(studioApi.agents).mockResolvedValue([agent()]);
  vi.mocked(studioApi.agent).mockResolvedValue(agent());
  vi.mocked(studioApi.catalog).mockResolvedValue([{ toolset: "ledger", description: "Sổ cái", ops }]);
  vi.mocked(studioApi.hooks).mockResolvedValue([]);
  vi.mocked(credentialsApi.list).mockResolvedValue({ items: [cred()], total: 1, limit: 100, offset: 0 });
});

describe("Studio", () => {
  it("tạo credential gửi secret; danh sách chỉ hiện masked_hint, DOM không chứa secret", async () => {
    vi.mocked(credentialsApi.create).mockResolvedValue(cred({ id: "c2", name: "Key phụ", masked_hint: "sk-…7890" }));
    const view = open("/studio?tab=credentials");
    const u = userEvent.setup();
    expect((await screen.findByTestId("credential-hint-c1")).textContent).toBe("sk-…7890");
    await u.click(screen.getByTestId("credential-add"));
    const dialog = await screen.findByRole("dialog");
    await u.type(within(dialog).getByLabelText("Tên"), "Key phụ");
    const secret = within(dialog).getByTestId("credential-secret") as HTMLInputElement;
    expect(secret.type).toBe("password");
    await u.type(secret, SECRET);
    await u.click(within(dialog).getByTestId("dialog-submit"));
    await waitFor(() => expect(credentialsApi.create).toHaveBeenCalled());
    expect(firstArg(credentialsApi.create)).toEqual({ name: "Key phụ", provider_id: null, secret: SECRET, weight: 1 });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(view.container.ownerDocument.body.innerHTML).not.toContain(SECRET);
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("gắn key lỗi → toast lỗi bằng mã đã dịch (không lộ message thô)", async () => {
    vi.mocked(credentialsApi.list).mockResolvedValue({ items: [cred(), cred({ id: "c2", name: "Key lạ", provider_id: "p2", masked_hint: "sk-…abcd" })], total: 2, limit: 100, offset: 0 });
    vi.mocked(studioApi.setKeys).mockRejectedValue(new ApiError({ message: "Key does not belong to the model's provider", status: 422, code: 6020 }));
    open("/studio?tab=agents&agent=ag1");
    const u = userEvent.setup();
    const panel = await screen.findByTestId("keys-panel");
    await u.click(await within(panel).findByLabelText(/Key lạ/));
    await u.click(within(panel).getByTestId("keys-save"));
    await waitFor(() => expect(studioApi.setKeys).toHaveBeenCalled());
    expect(firstArg(studioApi.setKeys)).toEqual({ agent_id: "ag1", keys: [{ credential_id: "c2", enabled: true }] });
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    const msg = vi.mocked(toast.error).mock.calls[0]?.[0];
    expect(msg).toBe(translate("err.6020"));
    expect(msg).not.toContain("Key does not belong");
  });

  it("override deny → tool rời danh sách hiệu lực sang danh sách bị cấm", async () => {
    const denied = agent({ overrides: [{ operation: "wallet_record", policy: "deny", locked_params: {}, default_params: {} }] });
    vi.mocked(studioApi.setOverride).mockResolvedValue(denied);
    open("/studio?tab=agents&agent=ag1");
    const u = userEvent.setup();
    const effective = await screen.findByTestId("effective-tools");
    expect(within(effective).getByTestId("tool-wallet_record")).toBeTruthy();
    expect(screen.queryByTestId("denied-tools")).toBeNull();
    vi.mocked(studioApi.agent).mockResolvedValue(denied); // lần tải lại sau khi lưu
    await u.selectOptions(screen.getByTestId("policy-wallet_record"), "deny");
    await waitFor(() => expect(studioApi.setOverride).toHaveBeenCalled());
    expect(firstArg(studioApi.setOverride)).toEqual({ agent_id: "ag1", operation: "wallet_record", policy: "deny", remove: false });
    const list = await screen.findByTestId("denied-tools");
    expect(within(list).getByTestId("tool-wallet_record")).toBeTruthy();
    expect(within(screen.getByTestId("effective-tools")).queryByTestId("tool-wallet_record")).toBeNull();
    expect(within(screen.getByTestId("effective-tools")).getByTestId("tool-wallet_list")).toBeTruthy();
  });

  it("hook chạy thử hiện kết quả (JsonView); không khớp thì hiện thông báo không khớp", async () => {
    vi.mocked(studioApi.testHook).mockResolvedValueOnce({ matched: true, blocked: false, message: null, approval: true, context: [], results: [{ action: "require_approval" }] });
    open("/studio?tab=agents&agent=ag1");
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("hook-add"));
    const dialog = await screen.findByRole("dialog");
    await u.click(within(dialog).getByTestId("hook-test"));
    await waitFor(() => expect(studioApi.testHook).toHaveBeenCalledWith(expect.objectContaining({ point: "before_tool", action: { action: "require_approval" } })));
    const result = await within(dialog).findByTestId("hook-test-result");
    expect(within(result).getByTestId("json-view").textContent).toContain("approval");

    vi.mocked(studioApi.testHook).mockResolvedValueOnce({ matched: false, blocked: false, message: null, approval: false, context: [], results: [] });
    await u.click(within(dialog).getByTestId("hook-test"));
    await waitFor(() => expect(within(dialog).getByTestId("hook-test-result").textContent).toContain("Không khớp điều kiện"));
  });

  it("admin thường vào /studio → /403", async () => {
    renderPage(null, {
      path: "/none",
      route: "/studio",
      user: me({ permissions: ["user.view", "user.manage", "role.manage"] }),
      extra: (
        <Route element={<RequireSuperadmin />}>
          <Route path="/studio" element={<StudioPage />} />
        </Route>
      ),
    });
    expect((await screen.findByTestId("where")).textContent).toBe("/403");
    expect(studioApi.agents).not.toHaveBeenCalled();
  });

  describe("route của orchestrator", () => {
    const orch = () => agent({ id: "ag1", slug: "assistant", name: "Trợ lý", kind: "orchestrator", toolsets: [] });
    const spec = (id: string, slug: string, name: string) => agent({ id, slug, name, kind: "specialist", toolsets: ["lookup"] });
    const routeRow = (slug: string, name: string, position: number, over: Record<string, unknown> = {}) => ({
      orchestrator_id: "ag1", agent_id: `sp-${slug}`, slug, name, intent: `Ý định ${slug}`, examples: ["ví dụ 1"], position, enabled: true, ...over,
    }); // fmt: skip

    beforeEach(() => {
      vi.mocked(studioApi.agent).mockResolvedValue(orch());
      vi.mocked(studioApi.agents).mockResolvedValue([orch(), spec("sp-personal", "personal", "Sổ cá nhân"), spec("sp-report", "report", "Báo cáo"), agent({ id: "orch2", slug: "orch2", name: "Điều phối 2", kind: "orchestrator" })]);
      vi.mocked(studioApi.routes).mockResolvedValue([routeRow("personal", "Sổ cá nhân", 0), routeRow("report", "Báo cáo", 1, { enabled: false })] as never);
    });

    it("orchestrator có routes-panel (theo position, route tắt có huy hiệu) và ẩn panel Tool", async () => {
      open("/studio?tab=agents&agent=ag1");
      const panel = await screen.findByTestId("routes-panel");
      await waitFor(() => expect(studioApi.routes).toHaveBeenCalledWith("ag1"));
      const personal = await within(panel).findByTestId("route-personal");
      const report = within(panel).getByTestId("route-report");
      expect(personal.compareDocumentPosition(report) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(personal.textContent).toContain("#0 · Ý định personal");
      expect(report.textContent).toContain("Đã tắt");
      expect(screen.queryByTestId("tools-panel")).toBeNull();
      expect(screen.getByTestId("keys-panel")).toBeTruthy();
    });

    it("chuyên gia: có panel Tool, không có routes-panel", async () => {
      vi.mocked(studioApi.agent).mockResolvedValue(spec("sp-personal", "personal", "Sổ cá nhân"));
      open("/studio?tab=agents&agent=sp-personal");
      expect(await screen.findByTestId("tools-panel")).toBeTruthy();
      expect(screen.queryByTestId("routes-panel")).toBeNull();
    });

    it("thêm route: đích chỉ là chuyên gia, gửi save_route đúng shape", async () => {
      vi.mocked(studioApi.saveRoute).mockResolvedValue(routeRow("report", "Báo cáo", 3) as never);
      open("/studio?tab=agents&agent=ag1");
      const u = userEvent.setup();
      await u.click(await screen.findByTestId("route-add"));
      const dialog = await screen.findByRole("dialog");
      const target = within(dialog).getByTestId("route-target") as HTMLSelectElement;
      expect([...target.options].map((o) => o.value)).toEqual(["sp-personal", "sp-report"]); // không có orchestrator nào
      await u.selectOptions(target, "sp-report");
      expect((within(dialog).getByTestId("dialog-submit") as HTMLButtonElement).disabled).toBe(true); // thiếu ý định
      await u.type(within(dialog).getByTestId("route-intent"), "  Xem tổng chi, báo cáo  ");
      await u.type(within(dialog).getByTestId("route-examples"), "tháng này chi bao nhiêu\n\n  top danh mục  ");
      const pos = within(dialog).getByLabelText("Thứ tự") as HTMLInputElement;
      await u.clear(pos);
      await u.type(pos, "3");
      await u.click(within(dialog).getByTestId("dialog-submit"));
      await waitFor(() => expect(studioApi.saveRoute).toHaveBeenCalled());
      expect(firstArg(studioApi.saveRoute)).toEqual({
        orchestrator_id: "ag1",
        agent_id: "sp-report",
        intent: "Xem tổng chi, báo cáo",
        examples: ["tháng này chi bao nhiêu", "top danh mục"],
        position: 3,
        enabled: true,
      });
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    });

    it("sửa route: khoá chuyên gia đích, bật / tắt gửi enabled", async () => {
      vi.mocked(studioApi.saveRoute).mockResolvedValue(routeRow("personal", "Sổ cá nhân", 0, { enabled: false }) as never);
      open("/studio?tab=agents&agent=ag1");
      const u = userEvent.setup();
      const row = await screen.findByTestId("route-personal");
      await u.click(within(row).getByRole("button", { name: "Sửa" }));
      const dialog = await screen.findByRole("dialog");
      expect((within(dialog).getByTestId("route-target") as HTMLSelectElement).disabled).toBe(true);
      expect((within(dialog).getByTestId("route-intent") as HTMLTextAreaElement).value).toBe("Ý định personal");
      await u.click(within(dialog).getByRole("checkbox"));
      await u.click(within(dialog).getByTestId("dialog-submit"));
      await waitFor(() => expect(studioApi.saveRoute).toHaveBeenCalled());
      expect(firstArg(studioApi.saveRoute)).toMatchObject({ orchestrator_id: "ag1", agent_id: "sp-personal", enabled: false, examples: ["ví dụ 1"] });
    });

    it("xoá route: xác nhận rồi gọi delete_route", async () => {
      vi.mocked(studioApi.deleteRoute).mockResolvedValue(undefined as never);
      open("/studio?tab=agents&agent=ag1");
      const u = userEvent.setup();
      await u.click(within(await screen.findByTestId("route-personal")).getByRole("button", { name: "Xoá" }));
      const dialog = await screen.findByRole("dialog");
      expect(dialog.textContent).toContain('Xoá "Sổ cá nhân"?');
      await u.click(within(dialog).getByRole("button", { name: "Xác nhận" }));
      await waitFor(() => expect(studioApi.deleteRoute).toHaveBeenCalled());
      expect((studioApi.deleteRoute as ReturnType<typeof vi.fn>).mock.calls[0]?.slice(0, 2)).toEqual(["ag1", "sp-personal"]);
    });

    it("danh sách agent: huy hiệu loại (Điều phối / Chuyên gia)", async () => {
      open("/studio?tab=agents");
      expect((await screen.findByTestId("agent-assistant")).textContent).toContain("Điều phối (router)");
      expect(screen.getByTestId("agent-personal").textContent).toContain("Chuyên gia");
    });

    it("chọn loại agent khi tạo mới → save_agent gửi kind", async () => {
      vi.mocked(studioApi.saveAgent).mockResolvedValue(orch());
      open("/studio?tab=agents&agent=new");
      const u = userEvent.setup();
      const kind = (await screen.findByTestId("agent-kind")) as HTMLSelectElement;
      expect(kind.value).toBe("specialist");
      expect([...kind.options].map((o) => o.value)).toEqual(["specialist", "orchestrator"]);
      await u.type(screen.getByLabelText("Tên"), "Điều phối mới");
      await u.type(screen.getByLabelText("Mã (slug)"), "orch-new");
      await u.selectOptions(kind, "orchestrator");
      await u.click(screen.getByTestId("agent-save"));
      await waitFor(() => expect(studioApi.saveAgent).toHaveBeenCalled());
      expect(firstArg(studioApi.saveAgent)).toMatchObject({ agent_id: null, slug: "orch-new", name: "Điều phối mới", kind: "orchestrator" });
    });
  });
});
