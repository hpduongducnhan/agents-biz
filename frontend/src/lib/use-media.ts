import { useSyncExternalStore } from "react";

const DESKTOP = "(min-width: 768px)"; // = breakpoint `md` của Tailwind
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

const subscribers = new Map<string, (cb: () => void) => () => void>();

function subscriber(query: string): (cb: () => void) => () => void {
  let sub = subscribers.get(query);
  if (!sub) {
    sub = (cb) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    };
    subscribers.set(query, sub);
  }
  return sub;
}

const matches = (query: string) => typeof window.matchMedia === "function" && window.matchMedia(query).matches;

/** Media query hiện có khớp không (đổi theo trình duyệt, không cần tải lại). */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(subscriber(query), () => matches(query), () => false);
}

/** Từ `md` trở lên? Danh sách dùng để chọn bảng (desktop) hay thẻ (điện thoại) — R16. */
export function useIsDesktop(): boolean {
  return useMedia(DESKTOP);
}

/** Người dùng bật giảm chuyển động ở hệ điều hành — tắt hiệu ứng (ui-system §1). */
export function useReducedMotion(): boolean {
  return useMedia(REDUCED_MOTION);
}
