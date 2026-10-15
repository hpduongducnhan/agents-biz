// @vitest-environment jsdom
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StudioAgent } from "@/features/agent/api";
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

const SA = me({ is_superadmin: true, permissions: [] });
const agent = (): StudioAgent => ({
  id: "ag1", slug: "assistant", name: "Trợ lý", kind: "chat", description: "", instructions: "", persona_shared: true, starters: [], model_id: "m1", model_name: "gpt-x",
  params_override: {}, recursion_limit: 25, timeout_sec: 90, key_strategy: "round_robin", key_cooldown_sec: 300, visible_to: "all", visible_roles: [],
  is_active: true, keys: [], limits: { per_minute: null, per_hour: null, per_day: null, tokens_per_day: null }, toolsets: [], overrides: [], hooks_count: 0, warnings: [],
}); // fmt: skip

const open = (route: string) => renderPage(<StudioPage />, { path: "/studio", route, user: SA });
const slot = async () => within(await screen.findByTestId("studio-actions"));

beforeEach(() => {
  setDesktop(false);
  vi.mocked(studioApi.providers).mockResolvedValue([{ id: "p1", name: "OpenAI", kind: "openai", base_url: null, extra_headers: {}, default_params: {}, status: "active", models_count: 1 }]);
  vi.mocked(studioApi.models).mockResolvedValue([]);
  vi.mocked(studioApi.agents).mockResolvedValue([agent()]);
  vi.mocked(studioApi.agent).mockResolvedValue(agent());
  vi.mocked(studioApi.catalog).mockResolvedValue([]);
  vi.mocked(studioApi.hooks).mockResolvedValue([]);
  vi.mocked(studioApi.persona).mockResolvedValue({ content: "" } as never);
  vi.mocked(credentialsApi.list).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
});

describe("Studio — nút cấp tab nằm ở hàng tab", () => {
  it.each([
    ["agents", ["agent-configure-all", "agent-add"]],
    ["providers", ["provider-add"]],
    ["credentials", ["credential-add"]],
    ["models", ["model-add", "model-import"]],
  ])("tab %s: nút nằm trong studio-actions, không nằm trong tabpanel", async (tab, ids) => {
    open(`/studio?tab=${tab}`);
    const bar = await slot();
    for (const id of ids) {
      expect(await bar.findByTestId(id)).toBeTruthy();
      expect(within(screen.getByRole("tabpanel")).queryByTestId(id)).toBeNull();
    }
    expect(bar.getAllByRole("button")).toHaveLength(ids.length);
  });

  it.each(["/studio?tab=persona", "/studio?tab=agents&agent=new"])("%s: không có nút cấp tab", async (route) => {
    open(route);
    const bar = await slot();
    if (route.includes("agent=new")) await screen.findByTestId("agent-kind");
    else await screen.findByRole("tabpanel");
    expect(bar.queryAllByRole("button")).toHaveLength(0);
  });

  it("bấm agent-add ở hàng tab → mở trình sửa agent mới", async () => {
    open("/studio?tab=agents");
    const u = userEvent.setup();
    await u.click(await (await slot()).findByTestId("agent-add"));
    expect(await screen.findByTestId("agent-kind")).toBeTruthy();
    expect(screen.getByTestId("agent-back")).toBeTruthy();
  });

  it("bấm provider-add ở hàng tab → mở dialog", async () => {
    open("/studio?tab=providers");
    const u = userEvent.setup();
    await u.click(await (await slot()).findByTestId("provider-add"));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("đổi tab: nút agents biến mất, provider-add xuất hiện", async () => {
    open("/studio?tab=agents");
    const u = userEvent.setup();
    expect(await (await slot()).findByTestId("agent-add")).toBeTruthy();
    await u.click(screen.getByTestId("studio-tab-providers"));
    const bar = await slot();
    expect(await bar.findByTestId("provider-add")).toBeTruthy();
    expect(bar.queryByTestId("agent-add")).toBeNull();
  });
});
