// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyEvent, newRun, type RunEvent } from "@/features/agent/store";
import { LiveTurn } from "@/pages/assistant/simple/LiveTurn";

import { setDesktop } from "../render";

const base = (seq: number, extra: Record<string, unknown>) => ({ run_id: "r1", session_id: "s1", seq, ...extra });
const REPLY = "Trợ lý trả lời khá dài để thấy chữ hiện dần từng chút một theo từng khung hình của trình duyệt nhé bạn";

function liveWith(streamFlag: boolean | undefined, text = REPLY) {
  const start: RunEvent = { event: "agent:start", data: base(1, streamFlag === undefined ? {} : { stream: streamFlag }) };
  const token: RunEvent = { event: "agent:token", data: base(2, { delta: text }) };
  return applyEvent(applyEvent(newRun("r1", "s1"), start).run, token).run;
}

function reducedMotion(on: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: on && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

const bubbleText = () => screen.getByTestId("live-run").textContent ?? "";
const mount = (live: ReturnType<typeof liveWith>, onGrow?: () => void) =>
  render(<LiveTurn live={live} deciding={false} onDecide={vi.fn()} onGrow={onGrow} />);

beforeEach(() => {
  vi.useFakeTimers();
  setDesktop(false); // matchMedia không khớp reduced-motion
});
afterEach(() => vi.useRealTimers());

describe("LiveTurn — chữ hiện đều tay", () => {
  it("stream bật: chữ dài dần qua các khung hình, data-stream=on, gọi onGrow", () => {
    const onGrow = vi.fn();
    mount(liveWith(true), onGrow);
    expect(screen.getByTestId("live-run").getAttribute("data-stream")).toBe("on");
    const first = bubbleText().length;
    expect(first).toBeLessThan(REPLY.length);
    act(() => void vi.advanceTimersByTime(100));
    const second = bubbleText().length;
    expect(second).toBeGreaterThan(first);
    act(() => void vi.advanceTimersByTime(100));
    expect(bubbleText().length).toBeGreaterThan(second);
    expect(onGrow).toHaveBeenCalled();
    act(() => void vi.advanceTimersByTime(1500));
    expect(bubbleText()).toContain(REPLY);
  });

  it("agent:start.stream=false: hiện đủ ngay, data-stream=off", () => {
    mount(liveWith(false));
    expect(screen.getByTestId("live-run").getAttribute("data-stream")).toBe("off");
    expect(bubbleText()).toContain(REPLY);
  });

  it("chưa biết stream (thiếu cờ) → coi là bật", () => {
    mount(liveWith(undefined));
    expect(screen.getByTestId("live-run").getAttribute("data-stream")).toBe("on");
    expect(bubbleText().length).toBeLessThan(REPLY.length);
  });

  it("prefers-reduced-motion: hiện đủ ngay dù stream bật", () => {
    reducedMotion(true);
    mount(liveWith(true));
    expect(bubbleText()).toContain(REPLY);
  });
});
