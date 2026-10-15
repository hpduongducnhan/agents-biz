/** Chạy trước mỗi file test: dọn DOM giữa các test component + bù API trình duyệt jsdom thiếu (Radix cần) + nạp từ điển. */
import { afterEach, vi } from "vitest";

if (typeof window !== "undefined") {
  const { cleanup } = await import("@testing-library/react");
  const { registerAll } = await import("@/lib/i18n/register");
  registerAll();
  const { clearTokens } = await import("@/lib/auth-tokens");
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    clearTokens();
    localStorage.clear();
  });
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  // jsdom chưa có PointerEvent → Radix (DropdownMenu, Select) không nhận pointerdown nút trái.
  if (!("PointerEvent" in window)) {
    class PointerEventStub extends MouseEvent {
      pointerType: string;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerType = init.pointerType ?? "mouse";
      }
    }
    Object.assign(window, { PointerEvent: PointerEventStub });
  }
}
