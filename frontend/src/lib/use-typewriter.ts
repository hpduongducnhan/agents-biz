import { useEffect, useRef, useState } from "react";

/** Tốc độ tối thiểu (ký tự / giây). */
export const BASE_CPS = 60;
/** Đang chạy: mỗi ký tự hiện chậm nhất `MAX_LAG_S` sau khi tới. */
export const MAX_LAG_S = 0.6;
/** Lượt đã xong: phần còn lại hiện hết trong khoảng này. */
export const FINISH_S = 0.3;
const FRAME_MS = 33; // ~30 lần vẽ / giây là đủ mượt cho chữ

/** Một đợt chữ tới: phải hiện hết `end` ký tự đầu trước mốc `deadline` (ms, theo `performance.now()`). */
export type Segment = { end: number; deadline: number };

/** Dấu tổ hợp, ZWNJ / ZWJ, chọn kiểu emoji — luôn đi cùng ký tự đứng trước. */
const isJoiner = (c: number) => (c >= 0x300 && c <= 0x36f) || c === 0x200c || c === 0x200d || c === 0xfe0e || c === 0xfe0f;

/** Mở rộng điểm cắt để không tách đôi cặp surrogate, dấu tổ hợp hay chuỗi emoji nối ZWJ. */
export function safeCut(text: string, n: number): number {
  let i = Math.max(0, Math.min(n, text.length));
  while (i < text.length) {
    const code = text.charCodeAt(i);
    const lowSurrogate = code >= 0xdc00 && code <= 0xdfff;
    const prevJoiner = i > 0 && text.charCodeAt(i - 1) === 0x200d;
    if (!lowSurrogate && !isJoiner(code) && !prevJoiner) break;
    i += 1;
  }
  return i;
}

/** Số ký tự nên hiện sau một khung `dtMs` tại thời điểm `now`: ít nhất `BASE_CPS`, và đi đều tới hạn của từng đợt
 *  chưa hiện xong — đợt nào tới hạn trong khung này thì hiện hết. Kết quả không vượt `total`. */
export function nextCount(shown: number, total: number, segments: readonly Segment[], now: number, dtMs: number): number {
  let need = shown + Math.max(1, Math.round((BASE_CPS * dtMs) / 1000));
  for (const s of segments) {
    if (s.end <= shown) continue;
    const left = s.deadline - now;
    need = Math.max(need, left <= dtMs ? s.end : shown + Math.ceil(((s.end - shown) * dtMs) / left));
  }
  return Math.min(need, total);
}

/** Chữ đang stream hiện đều tay: mỗi đợt chữ tới hiện xong chậm nhất `MAX_LAG_S` sau đó; lượt xong
 *  (`running = false`) hiện nốt trong `FINISH_S`. `enabled = false` (stream tắt, giảm chuyển động) → trả nguyên `target`. */
export function useTypewriter(target: string, { running, enabled }: { running: boolean; enabled: boolean }): string {
  const [shown, setShown] = useState(() => (enabled && running ? 0 : target.length)); // mở lại lượt đã xong → hiện đủ ngay
  const shownRef = useRef(shown);
  const segments = useRef<Segment[]>([]);

  useEffect(() => {
    if (!enabled) return;
    const now = performance.now();
    if (shownRef.current > target.length) {
      shownRef.current = 0; // chữ bị thay (hiếm) → hiện lại từ đầu
      segments.current = [];
    }
    const last = segments.current.at(-1)?.end ?? shownRef.current;
    if (target.length > last) segments.current.push({ end: target.length, deadline: now + MAX_LAG_S * 1000 });
    if (!running) for (const s of segments.current) s.deadline = Math.min(s.deadline, now + FINISH_S * 1000);

    let raf = 0;
    let prev = now;
    const tick = (t: number) => {
      const dt = t - prev;
      if (dt >= FRAME_MS) {
        prev = t;
        const next = safeCut(target, nextCount(shownRef.current, target.length, segments.current, t, dt));
        shownRef.current = next;
        segments.current = segments.current.filter((s) => s.end > next);
        setShown(next);
      }
      raf = shownRef.current < target.length ? requestAnimationFrame(tick) : 0;
    };
    if (shownRef.current < target.length) raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, running, enabled]);

  return enabled ? target.slice(0, Math.min(shown, target.length)) : target;
}
