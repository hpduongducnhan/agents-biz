// @vitest-environment jsdom
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentCard, SessionDetail } from "@/features/agent/api";
import { ApiError } from "@/lib/api/errors";
import { type RealtimeHandler, socketManager, useSocketStatusStore } from "@/lib/realtime/socket";
import AssistantPage from "@/pages/assistant/AssistantPage";

import { me, page } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/agent/api", () => ({
  agentApi: {
    agents: vi.fn(),
    send: vi.fn(),
    sessions: vi.fn(),
    session: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    cancel: vi.fn(),
    decide: vi.fn(),
    decideMany: vi.fn(),
    runEvents: vi.fn(),
  },
}));
const { agentApi } = await import("@/features/agent/api");
const { toast } = await import("sonner");

const agent: AgentCard = { id: "ag1", slug: "assistant", name: "Trợ lý", description: "", starters: [] };
const detail = (over: Partial<SessionDetail> = {}): SessionDetail => ({
  session: { id: "s1", user_id: "u1", title: "Phiên", entry_agent_id: "ag1", last_agent_id: "ag1", created_at: "2026-10-12T00:00:00Z", updated_at: "2026-10-12T00:00:00Z" },
  messages: [],
  open_run: null,
  approvals: [],
  last_run: null,
  agents: [],
  tool_titles: {},
  ...over,
});

const handlers = new Map<string, RealtimeHandler>();
const fire = (event: string, seq: number, data: Record<string, unknown> = {}) =>
  act(() => void handlers.get(event)?.({ run_id: "r1", session_id: "s1", seq, ...data }, undefined as never));

const open = (user = me({ is_superadmin: true })) => renderPage(<AssistantPage />, { path: "/assistant", route: "/assistant?view=debug", user }); // màn Gỡ lỗi (user thường vào màn đơn giản)
const send = async (text: string) => {
  const u = userEvent.setup();
  await u.type(await screen.findByTestId("chat-input"), text);
  await u.click(screen.getByTestId("chat-send"));
  return u;
};

beforeEach(() => {
  setDesktop(false);
  handlers.clear();
  vi.spyOn(socketManager, "on").mockImplementation((event, h) => (handlers.set(event, h), () => handlers.delete(event)));
  useSocketStatusStore.setState({ status: "connected" });
  vi.mocked(agentApi.agents).mockResolvedValue([agent]);
  vi.mocked(agentApi.sessions).mockResolvedValue(page([]) as never);
  vi.mocked(agentApi.session).mockResolvedValue(detail());
  vi.mocked(agentApi.runEvents).mockResolvedValue({ available: true, events: [] });
  vi.mocked(agentApi.send).mockResolvedValue({ session_id: "s1", run_id: "r1", message_id: "m1" });
  vi.mocked(agentApi.cancel).mockResolvedValue({ run_id: "r1", status: "cancelled" });
  vi.mocked(agentApi.decide).mockResolvedValue({ approval_id: "a1", run_id: "r1", status: "approved" });
});


const ask = (id: string, title = `Xoá ${id}`) =>
  fire("agent:approval", Number(id.slice(1)), { approval_id: id, call_id: `c-${id}`, name: "wallet.void", title, args: { transaction_id: `t-${id}` }, expires_at: "2099-01-01T00:00:00Z" });
const group = async () => {
  const u = await send("xoá hai giao dịch");
  await screen.findByTestId("live-run");
  ask("a1");
  ask("a2");
  return { u, grp: await screen.findByTestId("approval-group") };
};
const decided = (id: string, status: string) => ({ approval_id: id, status });

describe("Duyệt hàng loạt", () => {
  beforeEach(() => {
    vi.mocked(agentApi.decideMany).mockResolvedValue({ run_id: "r1", decided: [decided("a1", "approved"), decided("a2", "approved")], skipped: [], resumed: true } as never);
    vi.mocked(toast.info).mockClear();
  });

  it("1 yêu cầu → thẻ cũ, không có thẻ gom", async () => {
    open();
    await send("xoá");
    await screen.findByTestId("live-run");
    ask("a1");
    expect(await screen.findByTestId("approval-a1")).toBeTruthy();
    expect(screen.queryByTestId("approval-group")).toBeNull();
    expect(screen.queryByTestId("approve-all")).toBeNull();
  });

  it("≥ 2 yêu cầu → thẻ gom có tiêu đề, Duyệt tất cả, mỗi dòng một nút", async () => {
    open();
    const { grp } = await group();
    expect(grp.getAttribute("data-pending")).toBe("2");
    expect(grp.textContent).toContain("2 thao tác cần duyệt");
    expect(within(grp).getByTestId("approve-all")).toBeTruthy();
    expect(within(grp).getByTestId("approval-row-a1")).toBeTruthy();
    expect(within(grp).getByTestId("approve-a2")).toBeTruthy();
    expect(screen.queryByTestId("approval-a1")).toBeNull();
  });

  it("bấm dòng mở tham số", async () => {
    open();
    const { u } = await group();
    expect(screen.queryByTestId("approval-args")).toBeNull();
    await u.click(within(screen.getByTestId("approval-row-a1")).getByText("Xoá a1"));
    expect(screen.getByTestId("approval-row-a1").textContent).toContain("t-a1");
  });

  it("Duyệt tất cả gọi agent.decide_approvals đúng các id đang chờ", async () => {
    open();
    const { u } = await group();
    await u.click(screen.getByTestId("approve-all"));
    await waitFor(() => expect(agentApi.decideMany).toHaveBeenCalledWith("r1", ["a1", "a2"], true, null));
    expect(agentApi.decide).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("approval-group").textContent).toContain("Đã duyệt 2 · từ chối 0"));
  });

  it("Từ chối tất cả bắt buộc lý do rồi gửi approve=false + lý do", async () => {
    vi.mocked(agentApi.decideMany).mockResolvedValue({ run_id: "r1", decided: [decided("a1", "rejected"), decided("a2", "rejected")], skipped: [], resumed: true } as never);
    open();
    const { u } = await group();
    await u.click(screen.getByTestId("reject-all"));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Từ chối" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(agentApi.decideMany).not.toHaveBeenCalled();
    await u.type(within(dialog).getByTestId("reject-reason"), "Không đúng");
    await u.click(submit);
    await waitFor(() => expect(agentApi.decideMany).toHaveBeenCalledWith("r1", ["a1", "a2"], false, "Không đúng"));
    await waitFor(() => expect(screen.getByTestId("approval-group").textContent).toContain("Đã duyệt 0 · từ chối 2"));
  });

  it("nút từng dòng gọi agent.decide_approval; dòng còn lại vẫn chờ", async () => {
    vi.mocked(agentApi.decide).mockResolvedValue({ approval_id: "a1", run_id: "r1", status: "approved" });
    open();
    const { u } = await group();
    await u.click(screen.getByTestId("approve-a1"));
    await waitFor(() => expect(agentApi.decide).toHaveBeenCalledWith("a1", true, null));
    expect(agentApi.decideMany).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByTestId("approve-a1")).toBeNull());
    expect(screen.getByTestId("approval-group").getAttribute("data-pending")).toBe("1");
    expect(screen.getByTestId("approve-a2")).toBeTruthy();
  });

  it("đang gửi → mọi nút khoá, không gửi lần hai", async () => {
    vi.mocked(agentApi.decideMany).mockReturnValue(new Promise(() => {}));
    open();
    const { u } = await group();
    await u.click(screen.getByTestId("approve-all"));
    await waitFor(() => expect((screen.getByTestId("approve-all") as HTMLButtonElement).disabled).toBe(true));
    for (const id of ["reject-all", "approve-a1", "reject-a1", "approve-a2", "reject-a2"]) {
      expect((screen.getByTestId(id) as HTMLButtonElement).disabled).toBe(true);
    }
    await u.click(screen.getByTestId("approve-a2"));
    expect(agentApi.decide).not.toHaveBeenCalled();
    expect(agentApi.decideMany).toHaveBeenCalledTimes(1);
  });

  it("quyết hết → tiêu đề tóm tắt, dòng thu lại, bấm đầu thẻ để mở", async () => {
    open();
    const { u } = await group();
    await u.click(screen.getByTestId("approve-all"));
    const grp = await screen.findByText("Đã duyệt 2 · từ chối 0");
    expect(screen.queryByTestId("approval-row-a1")).toBeNull();
    expect(screen.queryByTestId("approve-all")).toBeNull();
    await u.click(grp);
    expect(screen.getByTestId("approval-row-a1")).toBeTruthy();
    expect(screen.queryByTestId("approve-a1")).toBeNull(); // hết chờ → nhãn trạng thái, không còn nút
  });

  it("skipped không rỗng → toast thông tin", async () => {
    vi.mocked(agentApi.decideMany).mockResolvedValue({ run_id: "r1", decided: [decided("a1", "approved")], skipped: ["a2"], resumed: false } as never);
    open();
    const { u } = await group();
    await u.click(screen.getByTestId("approve-all"));
    await waitFor(() => expect(toast.info).toHaveBeenCalledWith("1 thao tác đã được quyết trước đó"));
  });

  it("lỗi từ server → toast lỗi, nút mở lại", async () => {
    vi.mocked(agentApi.decideMany).mockRejectedValue(new ApiError({ message: "đã quyết", status: 409, code: 6008 }));
    open();
    const { u } = await group();
    await u.click(screen.getByTestId("approve-all"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    await waitFor(() => expect((screen.getByTestId("approve-all") as HTMLButtonElement).disabled).toBe(false));
  });
});
