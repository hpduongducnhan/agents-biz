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
    runEvents: vi.fn(),
  },
}));
const { agentApi } = await import("@/features/agent/api");

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

describe("AssistantPage", () => {
  it("gửi tin hiện ngay tin của tôi, rồi chữ chạy theo agent:token", async () => {
    open();
    await send("Chào bạn");
    expect((await screen.findByTestId("msg-pending")).textContent).toBe("Chào bạn");
    expect(agentApi.send).toHaveBeenCalledWith(expect.objectContaining({ agent_id: "ag1", content: "Chào bạn", session_id: null }));
    await waitFor(() => expect(screen.getByTestId("live-run")).toBeTruthy());
    fire("agent:start", 1);
    fire("agent:token", 2, { delta: "Xin " });
    fire("agent:token", 3, { delta: "chào" });
    expect(within(screen.getByTestId("live-run")).getByText("Xin chào")).toBeTruthy();
    fire("agent:token", 3, { delta: "chào" }); // trùng seq → không nhân đôi
    expect(within(screen.getByTestId("live-run")).getByText("Xin chào")).toBeTruthy();
  });

  it("bước tool running → done, mở xem tham số", async () => {
    open();
    await send("liệt kê ví");
    await screen.findByTestId("live-run");
    fire("agent:step", 1, { call_id: "c1", name: "wallet_list", title: "Liệt kê ví", status: "running", args: { limit: 5 } });
    const step = await screen.findByTestId("step-c1");
    expect(step.getAttribute("data-status")).toBe("running");
    expect(step.textContent).toContain("Liệt kê ví");
    fire("agent:step", 2, { call_id: "c1", name: "wallet_list", title: "Liệt kê ví", status: "done" });
    expect(screen.getByTestId("step-c1").getAttribute("data-status")).toBe("done");
    await userEvent.setup().click(within(screen.getByTestId("step-c1")).getByText("Liệt kê ví"));
    expect(within(screen.getByTestId("step-c1")).getByText("Tham số")).toBeTruthy();
    expect(within(screen.getByTestId("step-c1")).getByTestId("json-view").textContent).toContain("limit");
  });

  it("thẻ duyệt: Duyệt gọi decide_approval approve=true", async () => {
    open();
    await send("xoá ví");
    await screen.findByTestId("live-run");
    fire("agent:approval", 1, { approval_id: "a1", call_id: "c1", name: "wallet.delete", title: "Xoá ví", args: { id: "w1" }, expires_at: "2099-01-01T00:00:00Z" });
    const card = await screen.findByTestId("approval-a1");
    expect(card.textContent).toContain("Xoá ví");
    await userEvent.setup().click(within(card).getByTestId("approve-a1"));
    await waitFor(() => expect(agentApi.decide).toHaveBeenCalledWith("a1", true, null));
  });

  it("thẻ duyệt: Từ chối bắt buộc lý do", async () => {
    vi.mocked(agentApi.decide).mockResolvedValue({ approval_id: "a1", run_id: "r1", status: "rejected" });
    open();
    const u = await send("xoá ví");
    await screen.findByTestId("live-run");
    fire("agent:approval", 1, { approval_id: "a1", call_id: "c1", name: "wallet.delete", title: "Xoá ví", args: {}, expires_at: "2099-01-01T00:00:00Z" });
    await u.click(await screen.findByTestId("reject-a1"));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Từ chối" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await u.type(within(dialog).getByTestId("reject-reason"), "Không đúng ví");
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    await u.click(submit);
    await waitFor(() => expect(agentApi.decide).toHaveBeenCalledWith("a1", false, "Không đúng ví"));
  });

  it("Dừng gọi agent.cancel; agent:end cancelled → hết chạy", async () => {
    open();
    await send("làm lâu");
    await screen.findByTestId("live-run");
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("chat-stop"));
    await waitFor(() => expect(agentApi.cancel).toHaveBeenCalledWith("r1"));
    fire("agent:end", 1, { status: "cancelled", message_id: null });
    await waitFor(() => expect(screen.queryByTestId("live-run")).toBeNull());
    expect(screen.getByTestId("chat-send")).toBeTruthy();
  });

  it("429 mã 6001 hiện thông báo thử lại", async () => {
    vi.mocked(agentApi.send).mockRejectedValue(new ApiError({ message: "quá nhanh", status: 429, code: 6001, data: { retry_after_sec: 30 } }));
    open();
    await send("a");
    const notice = await screen.findByTestId("chat-notice-retry");
    expect(notice.textContent).toContain("thử lại");
    expect(screen.queryByTestId("msg-pending")).toBeNull();
  });

  it("6009: 'chưa được cấu hình'; link Studio chỉ cho superadmin", async () => {
    vi.mocked(agentApi.send).mockRejectedValue(new ApiError({ message: "x", status: 503, code: 6009 }));
    const first = open(me());
    await send("a");
    expect((await screen.findByTestId("chat-notice-notConfigured")).textContent).toContain("Trợ lý chưa được cấu hình");
    expect(screen.queryByRole("link", { name: "Mở Agent Studio" })).toBeNull();
    first.unmount();

    open(me({ is_superadmin: true, permissions: [] }));
    await send("a");
    await screen.findByTestId("chat-notice-notConfigured");
    expect(screen.getByRole("link", { name: "Mở Agent Studio" }).getAttribute("href")).toBe("/studio");
  });

  it("375px: ô nhập 16px (text-base), nút gửi / dừng cao ≥ 44px (h-11)", async () => {
    open();
    const input = await screen.findByTestId("chat-input");
    expect(input.className).toContain("text-base");
    expect(input.className).toContain("min-h-11");
    expect(screen.getByTestId("chat-send").className).toContain("h-11");
    await send("chạy");
    expect((await screen.findByTestId("chat-stop")).className).toContain("h-11");
  });

  it("realtime: ≥ 2 bước: dải 'Chuyển lần lượt' + mỗi chuyên gia một khối có nhãn đúng thứ tự, tool / thẻ duyệt vào đúng khối", async () => {
    open();
    await send("ghi 45k rồi cho tôi xem tổng chi");
    await screen.findByTestId("live-run");
    const personal = { agent_id: "ag-p", slug: "personal", name: "Sổ cá nhân" };
    const report = { agent_id: "ag-r", slug: "report", name: "Báo cáo" };
    fire("agent:start", 1);
    fire("agent:route", 2, { steps: [{ ...personal, task: "ghi 45k" }, { ...report, task: "tổng chi" }], clarify: null });
    expect((await screen.findByTestId("live-route")).textContent).toBe("Chuyển lần lượt: Sổ cá nhân → Báo cáo");
    fire("agent:step", 3, { call_id: "c1", name: "wallet_record_expense", title: "Ghi chi", status: "running", args: { amount: 45000 }, by: personal });
    fire("agent:token", 4, { delta: "Đã ghi ", by: personal });
    fire("agent:token", 5, { delta: "45.000 ₫", by: personal });
    fire("agent:token", 6, { delta: "Tháng này chi 1tr", by: report });
    const blocks = screen.getAllByTestId(/^live-block-/);
    expect(blocks.map((b) => b.getAttribute("data-testid"))).toEqual(["live-block-personal", "live-block-report"]);
    expect(within(blocks[0]!).getByText("Sổ cá nhân")).toBeTruthy();
    expect(within(blocks[0]!).getByText("Đã ghi 45.000 ₫")).toBeTruthy();
    expect(within(blocks[0]!).getByTestId("step-c1")).toBeTruthy();
    expect(within(blocks[1]!).getByText("Báo cáo")).toBeTruthy();
    expect(within(blocks[1]!).getByText("Tháng này chi 1tr")).toBeTruthy();
    expect(within(blocks[1]!).queryByTestId("step-c1")).toBeNull();
    fire("agent:approval", 7, { approval_id: "a1", call_id: "c2", name: "wallet.void", title: "Huỷ khoản", args: {}, expires_at: "2099-01-01T00:00:00Z", by: report });
    expect(within(await screen.findByTestId("live-block-report")).getByTestId("approval-a1")).toBeTruthy();
  });

  it("1 bước: không hiện dải chuyển; hỏi lại (clarify) hiện chữ ở khối chính không nhãn", async () => {
    open();
    await send("500k");
    await screen.findByTestId("live-run");
    fire("agent:route", 1, { steps: [{ agent_id: "ag-p", slug: "personal", name: "Sổ cá nhân", task: "" }], clarify: null });
    expect(screen.queryByTestId("live-route")).toBeNull();
  });

  it("realtime: hỏi lại (clarify): dải chuyển ẩn, câu hỏi hiện ở khối chính không nhãn", async () => {
    open();
    await send("500k");
    await screen.findByTestId("live-run");
    fire("agent:route", 1, { steps: [], clarify: "Bạn muốn ghi vào ví nào?" });
    fire("agent:token", 2, { delta: "Bạn muốn ghi vào ví nào?" });
    const main = await screen.findByTestId("live-block-main");
    expect(main.textContent).toBe("Bạn muốn ghi vào ví nào?");
    expect(screen.queryByTestId("live-route")).toBeNull();
  });

  it("≥ 2 bước (bù qua run_events): dải chuyển + 2 khối có nhãn đúng thứ tự, tool vào đúng khối", async () => {
    const personal = { agent_id: "ag-p", slug: "personal", name: "Sổ cá nhân" };
    const report = { agent_id: "ag-r", slug: "report", name: "Báo cáo" };
    const e = (event: string, seq: number, data: Record<string, unknown>) => ({ event, data: { run_id: "r1", session_id: "s1", seq, ...data } });
    vi.mocked(agentApi.runEvents).mockResolvedValue({
      available: true,
      events: [
        e("agent:start", 1, {}),
        e("agent:route", 2, { steps: [{ ...personal, task: "ghi" }, { ...report, task: "tổng" }], clarify: null }),
        e("agent:step", 3, { call_id: "c1", name: "wallet_list", title: "Liệt kê ví", status: "done", by: personal }),
        e("agent:token", 4, { delta: "Đã ghi", by: personal }),
        e("agent:token", 5, { delta: "Tổng 1tr", by: report }),
      ],
    } as never);
    open();
    await send("ghi 45k rồi xem tổng");
    expect((await screen.findByTestId("live-route")).textContent).toBe("Chuyển lần lượt: Sổ cá nhân → Báo cáo");
    const blocks = screen.getAllByTestId(/^live-block-/);
    expect(blocks.map((b) => b.getAttribute("data-testid"))).toEqual(["live-block-personal", "live-block-report"]);
    expect(within(blocks[0]!).getByText("Sổ cá nhân")).toBeTruthy();
    expect(within(blocks[0]!).getByText("Đã ghi")).toBeTruthy();
    expect(within(blocks[0]!).getByTestId("step-c1")).toBeTruthy();
    expect(within(blocks[1]!).getByText("Báo cáo")).toBeTruthy();
    expect(within(blocks[1]!).getByText("Tổng 1tr")).toBeTruthy();
    expect(within(blocks[1]!).queryByTestId("step-c1")).toBeNull();
  });

  it("lịch sử: nhãn chuyên gia (chỉ chuyên gia khác entry) + chip tool mở ra tham số và kết quả ghép từ tin tool", async () => {
    const msg = (id: string, seq: number, role: string, agent_id: string | null, content: Record<string, unknown>) => ({ id, seq, role, agent_id, content, run_id: "r0", created_at: "2026-10-12T00:00:00Z" });
    vi.mocked(agentApi.session).mockResolvedValue(
      detail({
        agents: [
          { id: "ag1", slug: "assistant", name: "Trợ lý", kind: "orchestrator" },
          { id: "ag-p", slug: "personal", name: "Sổ cá nhân", kind: "specialist" },
          { id: "ag-r", slug: "report", name: "Báo cáo", kind: "specialist" },
        ],
        messages: [
          msg("m1", 1, "user", null, { text: "ghi 45k rồi xem tổng" }),
          msg("m2", 2, "assistant", "ag-p", { text: "", tool_calls: [{ id: "tc1", name: "wallet_record_expense", args: { amount: 45000 } }] }),
          msg("m3", 3, "tool", "ag-p", { text: '{"id":"t1","amount":45000}', tool_call_id: "tc1", name: "wallet_record_expense", status: "success" }),
          msg("m4", 4, "assistant", "ag-p", { text: "Đã ghi 45.000 ₫" }),
          msg("m5", 5, "assistant", "ag-r", { text: "Tháng này chi 1tr" }),
          msg("m6", 6, "assistant", "ag1", { text: "Bạn muốn ghi vào ví nào?", kind: "clarify" }),
        ],
      }),
    );
    renderPage(<AssistantPage />, { path: "/assistant", route: "/assistant?session=s1&view=debug", user: me({ is_superadmin: true }) });
    const bubbles = await screen.findAllByTestId("msg-assistant");
    expect(bubbles).toHaveLength(4); // tin tool ẩn
    expect(screen.getAllByTestId("msg-agent").map((x) => x.textContent)).toEqual(["Sổ cá nhân", "Sổ cá nhân", "Báo cáo"]);
    expect(within(bubbles[3]!).queryByTestId("msg-agent")).toBeNull(); // entry (orchestrator) không có nhãn
    const chip = screen.getByTestId("call-tc1");
    await userEvent.setup().click(within(chip).getByText("wallet record expense"));
    const views = within(chip).getAllByTestId("json-view");
    expect(views[0]!.textContent).toContain("45000");
    expect(within(chip).getByText("Tham số")).toBeTruthy();
    expect(within(chip).getByText("Kết quả")).toBeTruthy();
    expect(views[1]!.textContent).toContain("t1");
  });

  it("khung tin nhắn tự cuộn: có phiên → scrollTop = scrollHeight; ô nhập nằm ngoài khung cuộn", async () => {
    const desc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { value: 500, configurable: true });
    try {
      const msg = (id: string, seq: number, role: string, text: string) => ({ id, seq, role, agent_id: "ag1", content: { text }, run_id: "r0", created_at: "2026-10-12T00:00:00Z" });
      vi.mocked(agentApi.session).mockResolvedValue(detail({ messages: [msg("m1", 1, "user", "xin chào"), msg("m2", 2, "assistant", "chào bạn")] }));
      renderPage(<AssistantPage />, { path: "/assistant", route: "/assistant?session=s1&view=debug", user: me({ is_superadmin: true }) });
      await screen.findAllByTestId("msg-assistant");
      const scroller = screen.getByTestId("chat-scroll");
      await waitFor(() => expect(scroller.scrollTop).toBe(500));
      expect(scroller.contains(screen.getByTestId("chat-input"))).toBe(false);
    } finally {
      if (desc) Object.defineProperty(HTMLElement.prototype, "scrollHeight", desc);
      else Reflect.deleteProperty(HTMLElement.prototype, "scrollHeight");
    }
  });

  it("màn trống (chưa có phiên): không tự cuộn xuống", async () => {
    const desc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { value: 500, configurable: true });
    try {
      open();
      const scroller = await screen.findByTestId("chat-scroll");
      await screen.findByTestId("chat-input");
      expect(scroller.scrollTop).toBe(0);
      expect(scroller.contains(screen.getByTestId("chat-input"))).toBe(false);
    } finally {
      if (desc) Object.defineProperty(HTMLElement.prototype, "scrollHeight", desc);
      else Reflect.deleteProperty(HTMLElement.prototype, "scrollHeight");
    }
  });
});
