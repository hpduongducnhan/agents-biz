// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentCard } from "@/features/agent/api";
import { ApiError } from "@/lib/api/errors";
import { socketManager, useSocketStatusStore } from "@/lib/realtime/socket";
import AssistantPage from "@/pages/assistant/AssistantPage";
import { ChatLimitNotice, noticeOf } from "@/pages/assistant/ChatNotice";

import { me, page } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/agent/api", () => ({
  agentApi: { agents: vi.fn(), send: vi.fn(), sessions: vi.fn(), session: vi.fn(), current: vi.fn(), runEvents: vi.fn(), cancel: vi.fn(), decide: vi.fn(), rename: vi.fn(), remove: vi.fn() },
}));
vi.mock("@/features/agent/guardApi", () => ({ guardApi: { chatLimits: vi.fn() } }));
const { agentApi } = await import("@/features/agent/api");
const { guardApi } = await import("@/features/agent/guardApi");

const win = (window: string, limit: number | null, used: number) => ({ window, limit, used, source: "default" as const, role: null });
const limits = (over: Record<string, unknown> = {}) => ({
  exempt: false,
  windows: [win("minute", 10, 0), win("hour", 100, 0), win("day", 400, 0)],
  blocked: null,
  ...over,
});
const blocked = (over: Record<string, unknown> = {}) => ({
  id: "b1",
  user: { id: "u1", email: "u1@test.local", name: "U" },
  until: "2026-10-14T12:00:00Z",
  reason: "Spam thử E2E",
  source: "manual",
  created_by: "Root",
  created_at: "2026-10-14T11:00:00Z",
  lifted_at: null,
  lifted_by: null,
  active: true,
  ...over,
});
const agent: AgentCard = { id: "ag1", slug: "assistant", name: "Trợ lý", description: "", starters: [] };

beforeEach(() => {
  setDesktop(false);
  vi.spyOn(socketManager, "on").mockImplementation(() => () => undefined);
  useSocketStatusStore.setState({ status: "connected" });
  vi.mocked(agentApi.agents).mockResolvedValue([agent]);
  vi.mocked(agentApi.sessions).mockResolvedValue(page([]) as never);
  vi.mocked(agentApi.current).mockResolvedValue(null as never);
  vi.mocked(agentApi.runEvents).mockResolvedValue({ available: true, events: [] });
  vi.mocked(guardApi.chatLimits).mockResolvedValue(limits() as never);
});

describe("noticeOf 6022", () => {
  it("403 · 6022 → kind blocked", () => {
    const err = new ApiError({ message: "x", status: 403, code: 6022, data: { until: null, reason: "r", source: "auto" } });
    expect(noticeOf(err)).toEqual({ kind: "blocked" });
  });
});

describe("ChatLimitNotice", () => {
  it("bị chặn: hộp chat-blocked có lý do", () => {
    render(<ChatLimitNotice guard={{ blocked: blocked() as never, leftToday: null }} />);
    expect(screen.getByTestId("chat-blocked").textContent).toContain("Spam thử E2E");
  });

  it("bị chặn không hạn: câu 'tới khi quản trị mở chặn'", () => {
    render(<ChatLimitNotice guard={{ blocked: blocked({ until: null }) as never, leftToday: null }} />);
    expect(screen.getByTestId("chat-blocked").textContent).toContain("tới khi quản trị mở chặn");
  });

  it("sắp hết hạn mức ngày: hiện 'Còn N tin'", () => {
    render(<ChatLimitNotice guard={{ blocked: null, leftToday: 3 }} />);
    expect(screen.getByTestId("chat-left-today").textContent).toContain("3");
  });

  it("bình thường: không hiện gì", () => {
    const { container } = render(<ChatLimitNotice guard={{ blocked: null, leftToday: null }} />);
    expect(container.textContent).toBe("");
  });
});

describe("SimpleChat + hạn mức", () => {
  const open = () => renderPage(<AssistantPage />, { path: "/assistant", route: "/assistant", user: me() });

  it("đang bị chặn: có chat-blocked và ô nhập bị khoá", async () => {
    vi.mocked(guardApi.chatLimits).mockResolvedValue(limits({ blocked: blocked() }) as never);
    open();
    expect(await screen.findByTestId("chat-blocked")).toBeTruthy();
    expect((screen.getByTestId("chat-input") as HTMLTextAreaElement).disabled).toBe(true);
  });

  it("không bị chặn: ô nhập bật, không có hộp chặn; còn ít tin ngày → gợi ý", async () => {
    vi.mocked(guardApi.chatLimits).mockResolvedValue(limits({ windows: [win("minute", 10, 0), win("hour", 100, 90), win("day", 400, 395)] }) as never);
    open();
    expect((await screen.findByTestId("chat-left-today")).textContent).toContain("5");
    expect(screen.queryByTestId("chat-blocked")).toBeNull();
    await waitFor(() => expect((screen.getByTestId("chat-input") as HTMLTextAreaElement).disabled).toBe(false));
  });

  it("chưa gần hạn mức: không có gợi ý", async () => {
    open();
    await screen.findByTestId("chat-input");
    await waitFor(() => expect(guardApi.chatLimits).toHaveBeenCalled());
    expect(screen.queryByTestId("chat-left-today")).toBeNull();
  });
});
