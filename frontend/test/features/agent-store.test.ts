// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { agentApi, type SessionDetail } from "@/features/agent/api";
import { applyEvent, applyMany, newRun, type RunEvent, type RunEventName, withApprovals } from "@/features/agent/store";
import { useRunStream } from "@/features/agent/useRunStream";
import { type RealtimeHandler, socketManager, useSocketStatusStore } from "@/lib/realtime/socket";

vi.mock("@/features/agent/api", async (orig) => {
  const real = await orig<typeof import("@/features/agent/api")>();
  return { ...real, agentApi: { ...real.agentApi, runEvents: vi.fn() } };
});

const ev = (event: RunEventName, seq: number, extra: Record<string, unknown> = {}): RunEvent => ({
  event,
  data: { run_id: "r1", session_id: "s1", seq, ...extra },
});
const tok = (seq: number, delta: string) => ev("agent:token", seq, { delta });

describe("store: applyEvent / applyMany", () => {
  it("token gom theo seq, sự kiện cũ / trùng seq bị bỏ", () => {
    let run = newRun("r1", "s1");
    for (const e of [ev("agent:start", 1), tok(2, "Xin "), tok(3, "chào")]) run = applyEvent(run, e).run;
    expect(run.text).toBe("Xin chào");
    expect(run.lastSeq).toBe(3);
    const dup = applyEvent(run, tok(3, "chào"));
    const old = applyEvent(run, tok(1, "x"));
    expect(dup).toEqual({ run, gap: false });
    expect(old).toEqual({ run, gap: false });
    expect(dup.run.text).toBe("Xin chào");
  });

  it("seq nhảy → gap, không áp; applyMany sắp theo seq và dừng ở chỗ hở", () => {
    const run = applyEvent(newRun("r1", "s1"), ev("agent:start", 1)).run;
    expect(applyEvent(run, tok(3, "c")).gap).toBe(true);
    const out = applyMany(run, [tok(4, "d"), tok(3, "c"), tok(2, "b"), tok(6, "f")]);
    expect(out.text).toBe("bcd");
    expect(out.lastSeq).toBe(4);
  });

  it("bước tool: cập nhật cùng call_id, giữ args cũ khi sự kiện sau không có args", () => {
    let run = newRun("r1", "s1");
    run = applyEvent(run, ev("agent:step", 1, { call_id: "c1", name: "wallet_list", title: "Liệt kê ví", status: "running", args: { a: 1 } })).run;
    run = applyEvent(run, ev("agent:step", 2, { call_id: "c1", name: "wallet_list", status: "done", preview: "ok" })).run;
    expect(run.steps).toEqual([{ callId: "c1", name: "wallet_list", title: "wallet_list", status: "done", args: { a: 1 }, preview: "ok" }]);
  });

  it("agent:end chốt (done / cancelled, messageId); agent:error → failed kèm mã", () => {
    const base = newRun("r1", "s1");
    const done = applyEvent(base, ev("agent:end", 1, { status: "done", message_id: "m1" })).run;
    expect(done).toMatchObject({ status: "done", messageId: "m1" });
    expect(applyEvent(base, ev("agent:end", 1, { status: "cancelled" })).run.status).toBe("cancelled");
    expect(applyEvent(base, ev("agent:error", 1, { code: 6011, message: "hỏng" })).run).toMatchObject({
      status: "failed",
      error: { code: 6011, message: "hỏng" },
    });
  });

  it("thẻ duyệt: agent:approval → waiting; approval_decided → running + trạng thái", () => {
    let run = applyEvent(newRun("r1", "s1"), ev("agent:approval", 1, { approval_id: "a1", call_id: "c1", name: "wallet.delete", title: "Xoá ví", args: { id: 1 } })).run;
    expect(run.status).toBe("waiting");
    expect(run.approvals[0]).toMatchObject({ approvalId: "a1", status: "pending", title: "Xoá ví" });
    run = applyEvent(run, ev("agent:approval_decided", 2, { approval_id: "a1", status: "rejected", reason: "không" })).run;
    expect(run.status).toBe("running");
    expect(run.approvals[0]).toMatchObject({ status: "rejected", reason: "không" });
  });

  it("withApprovals dựng thẻ từ hàng API; còn pending → waiting", () => {
    const rows = [
      { id: "a1", tool_call_id: "c1", operation: "wallet.delete", args: { x: 1 }, expires_at: "2026-10-12T01:00:00Z", status: "pending", reason: null },
      { id: "a2", tool_call_id: "c2", operation: "wallet.update", args: {}, expires_at: "2026-10-12T01:00:00Z", status: "approved", reason: null },
    ] as unknown as SessionDetail["approvals"];
    const run = withApprovals(newRun("r1", "s1"), rows);
    expect(run.status).toBe("waiting");
    expect(run.approvals.map((a) => [a.approvalId, a.callId, a.name, a.status])).toEqual([
      ["a1", "c1", "wallet.delete", "pending"],
      ["a2", "c2", "wallet.update", "approved"],
    ]);
    expect(withApprovals(newRun("r1", "s1"), [rows[1]!]).status).toBe("running");
  });
});

describe("store: router + khối theo chuyên gia", () => {
  const personal = { agent_id: "a-p", slug: "personal", name: "Sổ cá nhân" };
  const report = { agent_id: "a-r", slug: "report", name: "Báo cáo" };

  it("agent:route lưu các bước (kèm task) và câu hỏi lại", () => {
    const run = applyEvent(
      newRun("r1", "s1"),
      ev("agent:route", 1, { steps: [{ ...personal, task: "ghi 45k" }, { ...report, task: "tổng chi" }], clarify: null }),
    ).run;
    expect(run.route).toEqual({ steps: [{ ...personal, task: "ghi 45k" }, { ...report, task: "tổng chi" }], clarify: null });
    expect(run.lastSeq).toBe(1);
    const ask = applyEvent(newRun("r1", "s1"), ev("agent:route", 1, { steps: [], clarify: "Ví nào?" })).run;
    expect(ask.route).toEqual({ steps: [], clarify: "Ví nào?" });
  });

  it("token mang `by` → mỗi chuyên gia một khối theo thứ tự; cùng chuyên gia thì nối tiếp", () => {
    let run = applyMany(newRun("r1", "s1"), [
      ev("agent:start", 1),
      ev("agent:route", 2, { steps: [{ ...personal, task: "a" }, { ...report, task: "b" }], clarify: null }),
      tok(3, "Đã "),
    ]);
    run = applyMany(run, [
      { event: "agent:token", data: { run_id: "r1", session_id: "s1", seq: 4, delta: "ghi", by: personal } },
      { event: "agent:token", data: { run_id: "r1", session_id: "s1", seq: 5, delta: " xong", by: personal } },
      { event: "agent:token", data: { run_id: "r1", session_id: "s1", seq: 6, delta: "Tổng 1tr", by: report } },
    ]);
    expect(run.blocks.map((b) => [b.by?.slug, b.text])).toEqual([
      [undefined, "Đã "],
      ["personal", "ghi xong"],
      ["report", "Tổng 1tr"],
    ]);
    expect(run.text).toBe("Đã ghi xongTổng 1tr");
  });

  it("agent đơn (không `by`): một khối duy nhất không nhãn", () => {
    const run = applyMany(newRun("r1", "s1"), [tok(1, "Xin "), tok(2, "chào")]);
    expect(run.blocks).toEqual([{ by: undefined, text: "Xin chào" }]);
  });

  it("bước tool và thẻ duyệt có `by`: mở khối của chuyên gia, giữ `by` trên bước / thẻ", () => {
    let run = applyEvent(newRun("r1", "s1"), {
      event: "agent:step",
      data: { run_id: "r1", session_id: "s1", seq: 1, call_id: "c1", name: "wallet_list", status: "running", by: personal },
    }).run;
    expect(run.steps[0]?.by).toEqual(personal);
    expect(run.blocks).toEqual([{ by: personal, text: "" }]);
    run = applyEvent(run, {
      event: "agent:step",
      data: { run_id: "r1", session_id: "s1", seq: 2, call_id: "c1", name: "wallet_list", status: "done", by: personal },
    }).run;
    expect(run.blocks).toHaveLength(1); // cập nhật bước cũ không mở khối mới
    run = applyEvent(run, {
      event: "agent:approval",
      data: { run_id: "r1", session_id: "s1", seq: 3, approval_id: "a1", call_id: "c2", name: "wallet_void", title: "Huỷ", args: {}, by: report },
    }).run;
    expect(run.status).toBe("waiting");
    expect(run.approvals[0]?.by).toEqual(report);
    expect(run.blocks.map((b) => b.by?.slug)).toEqual(["personal", "report"]);
  });

  it("`by` thiếu slug bị bỏ qua (không tạo nhãn rỗng)", () => {
    const run = applyEvent(newRun("r1", "s1"), {
      event: "agent:token",
      data: { run_id: "r1", session_id: "s1", seq: 1, delta: "x", by: { name: "?" } },
    }).run;
    expect(run.blocks).toEqual([{ by: undefined, text: "x" }]);
  });
});

describe("useRunStream", () => {
  const handlers = new Map<string, RealtimeHandler>();
  const fire = (e: RunEvent) => act(() => void handlers.get(e.event)?.(e.data, undefined as never));
  let client: QueryClient;
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);

  beforeEach(() => {
    handlers.clear();
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(socketManager, "on").mockImplementation((event, h) => (handlers.set(event, h), () => handlers.delete(event)));
    useSocketStatusStore.setState({ status: "connected" });
    vi.mocked(agentApi.runEvents).mockResolvedValue({ available: true, events: [] } as never);
  });

  it("start rồi nhận token theo seq; seq nhảy → gọi run_events after_seq và ghép đúng thứ tự", async () => {
    const { result } = renderHook(() => useRunStream("s1", undefined, vi.fn()), { wrapper });
    act(() => result.current.start("r1", "s1"));
    await waitFor(() => expect(agentApi.runEvents).toHaveBeenCalledWith("r1", 0));
    fire(tok(1, "a"));
    expect(result.current.live?.text).toBe("a");
    vi.mocked(agentApi.runEvents).mockResolvedValueOnce({ available: true, events: [tok(2, "b"), tok(3, "c")] } as never);
    fire(tok(4, "d")); // hở 2, 3
    await waitFor(() => expect(agentApi.runEvents).toHaveBeenLastCalledWith("r1", 1));
    await waitFor(() => expect(result.current.live?.text).toBe("abc"));
    fire(tok(4, "d"));
    expect(result.current.live?.text).toBe("abcd");
  });

  it("sự kiện của lượt khác bị bỏ; agent:end → làm mới phiên và xoá live", async () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useRunStream("s1", undefined, vi.fn()), { wrapper });
    act(() => result.current.start("r1", "s1"));
    fire({ event: "agent:token", data: { run_id: "rX", session_id: "s1", seq: 1, delta: "lạ" } });
    expect(result.current.live?.text).toBe("");
    fire(ev("agent:end", 1, { status: "done", message_id: "m1" }));
    await waitFor(() => expect(result.current.live).toBeNull());
    expect(spy).toHaveBeenCalled();
  });

  it("socket nối lại khi đang có run → bù bằng run_events", async () => {
    useSocketStatusStore.setState({ status: "offline" });
    const { result } = renderHook(() => useRunStream("s1", undefined, vi.fn()), { wrapper });
    act(() => result.current.start("r1", "s1"));
    await waitFor(() => expect(agentApi.runEvents).toHaveBeenCalledTimes(1));
    fire(tok(1, "a"));
    vi.mocked(agentApi.runEvents).mockResolvedValueOnce({ available: true, events: [tok(2, "b")] } as never);
    act(() => useSocketStatusStore.setState({ status: "connected" }));
    await waitFor(() => expect(agentApi.runEvents).toHaveBeenLastCalledWith("r1", 1));
    await waitFor(() => expect(result.current.live?.text).toBe("ab"));
  });

  it("mở phiên giữa lượt (open_run) → dựng lại + bù; bộ đệm hết hạn → đọc lại phiên", async () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    vi.mocked(agentApi.runEvents).mockResolvedValue({ available: false, events: [] } as never);
    const detail = { open_run: { id: "r9" }, approvals: [] } as unknown as SessionDetail;
    renderHook(() => useRunStream("s1", detail, vi.fn()), { wrapper });
    await waitFor(() => expect(agentApi.runEvents).toHaveBeenCalledWith("r9", 0));
    await waitFor(() => expect(spy).toHaveBeenCalled());
  });
});

describe("store: agent:start.stream", () => {
  it("stream=false → live.stream=false; true hoặc thiếu → true", () => {
    expect(applyEvent(newRun("r1", "s1"), ev("agent:start", 1, { stream: false })).run.stream).toBe(false);
    expect(applyEvent(newRun("r1", "s1"), ev("agent:start", 1, { stream: true })).run.stream).toBe(true);
    expect(applyEvent(newRun("r1", "s1"), ev("agent:start", 1)).run.stream).toBe(true);
  });
});
