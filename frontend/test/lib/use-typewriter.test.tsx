// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BASE_CPS, FINISH_S, MAX_LAG_S, nextCount, type Segment, safeCut, useTypewriter } from "@/lib/use-typewriter";

describe("safeCut — không cắt giữa ký tự", () => {
  it("cặp surrogate: cắt giữa emoji đẩy ra sau emoji", () => {
    const s = "ab😀cd";
    expect(safeCut(s, 3)).toBe(4);
    expect(safeCut(s, 2)).toBe(2);
    expect(safeCut(s, 4)).toBe(4);
  });

  it("dấu tổ hợp tiếng Việt đi cùng chữ cái đứng trước", () => {
    const s = "Tiếng Việt"; // ê + sắc, ẹ + mũ ở dạng tổ hợp
    const cut = safeCut(s, 4);
    expect(s.slice(cut - 1, cut)).not.toBe("");
    expect(/^[̀-ͯ]/.test(s.slice(cut))).toBe(false);
    for (let n = 0; n <= s.length; n++) expect(/^[̀-ͯ]/.test(s.slice(safeCut(s, n)))).toBe(false);
  });

  it("chuỗi emoji ZWJ gia đình không bị tách", () => {
    const s = "Chào 👨‍👩‍👧 bạn";
    const start = s.indexOf("👨");
    const end = start + "👨‍👩‍👧".length;
    for (let n = start + 1; n < end; n++) expect(safeCut(s, n)).toBe(end);
    expect(safeCut(s, start)).toBe(start);
    expect(safeCut(s, end)).toBe(end);
  });

  it("biên: âm → 0, quá dài → độ dài", () => {
    expect(safeCut("abc", -5)).toBe(0);
    expect(safeCut("abc", 99)).toBe(3);
  });
});

const FRAME = 33;
const base = Math.round((BASE_CPS * FRAME) / 1000);

describe("nextCount (hạn chót theo đợt)", () => {
  it("không có đợt nào chờ → tốc độ nền BASE_CPS, tối thiểu 1 ký tự", () => {
    expect(nextCount(10, 1000, [], 0, FRAME)).toBe(10 + base);
    expect(nextCount(10, 1000, [], 0, 1)).toBe(11);
  });

  it("đợt tới hạn trong khung này → nhảy tới end", () => {
    const seg: Segment[] = [{ end: 400, deadline: 100 }];
    expect(nextCount(0, 400, seg, 100 - FRAME, FRAME)).toBe(400);
    expect(nextCount(0, 400, seg, 90, FRAME)).toBe(400);
    expect(nextCount(0, 400, seg, 200, FRAME)).toBe(400); // quá hạn
  });

  it("chưa tới hạn → tiến đều ceil(còn thiếu × dt / thời gian còn)", () => {
    const seg: Segment[] = [{ end: 400, deadline: 600 }];
    expect(nextCount(0, 400, seg, 0, FRAME)).toBe(Math.ceil((400 * FRAME) / 600));
    expect(nextCount(100, 400, seg, 300, FRAME)).toBe(100 + Math.ceil((300 * FRAME) / 300));
  });

  it("nhiều đợt: theo đợt đòi hỏi nhiều nhất; đợt đã hiện xong bị bỏ qua", () => {
    const segs: Segment[] = [
      { end: 50, deadline: 1000 },
      { end: 300, deadline: 60 },
      { end: 500, deadline: 5000 },
    ];
    expect(nextCount(0, 500, segs, 30, FRAME)).toBe(300);
    expect(nextCount(300, 500, segs, 30, FRAME)).toBe(300 + Math.max(base, Math.ceil((200 * FRAME) / 4970)));
    expect(nextCount(500, 500, segs, 30, FRAME)).toBe(500);
  });

  it("không bao giờ vượt total", () => {
    expect(nextCount(0, 3, [{ end: 400, deadline: 0 }], 0, FRAME)).toBe(3);
    expect(nextCount(5, 5, [], 0, FRAME)).toBe(5);
  });
});

describe("useTypewriter — hạn chót cứng", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  const text400 = "x".repeat(400);
  const SLACK = 70; // một khung (33 ms) + bước rAF của fake timer

  it("enabled=false → trả nguyên target ngay", () => {
    const { result } = renderHook(() => useTypewriter(text400, { running: true, enabled: false }));
    expect(result.current).toBe(text400);
  });

  it("mở lại lượt đã xong (running=false lúc mount) → hiện đủ ngay, không chạy lại chữ", () => {
    const { result } = renderHook(() => useTypewriter(text400, { running: false, enabled: true }));
    expect(result.current).toBe(text400);
  });

  it("400 ký tự: bắt đầu rỗng, tăng dần, hiện đủ trước MAX_LAG_S + 1 khung", () => {
    const { result } = renderHook(() => useTypewriter(text400, { running: true, enabled: true }));
    expect(result.current).toBe("");
    const lens: number[] = [];
    for (let t = 0; t < MAX_LAG_S * 1000 + SLACK; t += 16) {
      act(() => void vi.advanceTimersByTime(16));
      lens.push(result.current.length);
    }
    for (let i = 1; i < lens.length; i++) expect(lens[i] ?? 0).toBeGreaterThanOrEqual(lens[i - 1] ?? 0);
    expect(new Set(lens).size).toBeGreaterThan(5);
    expect(lens[Math.floor(lens.length / 2)]).toBeLessThan(400);
    expect(result.current).toBe(text400);
  });

  it("running=false → phần còn lại hiện đủ trong FINISH_S + 1 khung", () => {
    const { result, rerender } = renderHook(({ r }) => useTypewriter(text400, { running: r, enabled: true }), { initialProps: { r: true } });
    act(() => void vi.advanceTimersByTime(100));
    expect(result.current.length).toBeLessThan(400);
    rerender({ r: false });
    act(() => void vi.advanceTimersByTime(FINISH_S * 1000 + SLACK));
    expect(result.current).toBe(text400);
  });

  it("chữ liên tục tới: mỗi đợt hiện đủ không quá MAX_LAG_S + 1 khung sau khi tới", () => {
    const { result, rerender } = renderHook(({ t }) => useTypewriter(t, { running: true, enabled: true }), { initialProps: { t: "" } });
    const arrivals: { len: number; at: number; done?: number }[] = [];
    let text = "";
    let clock = 0;
    const advance = (ms: number) => {
      for (let k = 0; k < ms; k += 15) {
        act(() => void vi.advanceTimersByTime(15));
        clock += 15;
        for (const a of arrivals) if (a.done === undefined && result.current.length >= a.len) a.done = clock;
      }
    };
    for (let step = 0; step < 20; step++) {
      text += "a".repeat(30);
      arrivals.push({ len: text.length, at: clock });
      rerender({ t: text });
      advance(90);
    }
    advance(MAX_LAG_S * 1000 + SLACK);
    for (const a of arrivals) {
      expect(a.done, `đợt ${a.len} chưa hiện đủ`).toBeDefined();
      expect((a.done ?? clock) - a.at, `đợt ${a.len}`).toBeLessThanOrEqual(MAX_LAG_S * 1000 + SLACK);
    }
    expect(result.current).toBe(text);
  });

  it("target bị thay bằng chuỗi ngắn hơn → không vượt độ dài", () => {
    const { result, rerender } = renderHook(({ t }) => useTypewriter(t, { running: true, enabled: true }), { initialProps: { t: "z".repeat(200) } });
    act(() => void vi.advanceTimersByTime(1000));
    rerender({ t: "ngắn" });
    act(() => void vi.advanceTimersByTime(700));
    expect(result.current).toBe("ngắn");
  });
});
