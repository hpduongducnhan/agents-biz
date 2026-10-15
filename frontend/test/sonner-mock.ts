import { vi } from "vitest";

/** `sonner` giả — đọc lại toast đã gọi trong test. */
export const toast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() });
export const Toaster = () => null;
