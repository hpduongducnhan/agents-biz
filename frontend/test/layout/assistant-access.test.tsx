// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildNav } from "@/layout/nav";
import { MobileDock } from "@/layout/MobileDock";
import { canUseAssistant } from "@/lib/auth/permissions";
import AssistantPage from "@/pages/assistant/AssistantPage";

import { me } from "../fixtures";
import { renderPage } from "../render";

vi.mock("@/features/agent/api", () => ({ agentApi: { agents: vi.fn().mockResolvedValue([]) } }));
const { agentApi } = await import("@/features/agent/api");

const off = me({ tenant: { id: "t2", name: "Acme", slug: "acme", agent_enabled: false } });
const mainIds = (user: Parameters<typeof buildNav>[0]) => buildNav(user).find((s) => s.key === "main")?.items.map((i) => i.id);

describe("Trợ lý theo tổ chức (D22)", () => {
  it("canUseAssistant: cần agent.chat + tổ chức bật; superadmin luôn được", () => {
    expect(canUseAssistant(me())).toBe(true);
    expect(canUseAssistant(off)).toBe(false);
    expect(canUseAssistant(me({ permissions: [] }))).toBe(false);
    expect(canUseAssistant(me({ ...off, is_superadmin: true }))).toBe(true);
    expect(canUseAssistant(null)).toBe(false);
  });

  it("menu chính + nút nổi ẩn Trợ lý khi tổ chức tắt", () => {
    expect(mainIds(me())).toEqual(["overview", "assistant"]);
    expect(mainIds(off)).toEqual(["overview"]);
    const view = renderPage(<MobileDock />, { user: me() });
    expect(screen.getByTestId("dock-assistant")).toBeTruthy();
    view.unmount();
    renderPage(<MobileDock />, { user: off });
    expect(screen.queryByTestId("mobile-dock")).toBeNull();
  });

  it("trang Trợ lý báo đang tắt, không gọi danh sách agent", async () => {
    renderPage(<AssistantPage />, { path: "/assistant", route: "/assistant", user: off });
    expect(await screen.findByText(/Trợ lý đang tắt cho tổ chức của bạn/)).toBeTruthy();
    expect(agentApi.agents).not.toHaveBeenCalled();
  });
});
