/** PWA: đăng ký service worker ở bản build (`/sw.js` — cache file tĩnh, không cache API) và giữ sự kiện
 *  `beforeinstallprompt` để hướng dẫn "Thêm vào màn hình chính" có nút cài ngay khi trình duyệt cho cài. */
import { create } from "zustand";

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };

export const usePwaStore = create<{ prompt: InstallEvent | null }>(() => ({ prompt: null }));

export function registerPwa(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    usePwaStore.setState({ prompt: e as InstallEvent });
  });
  window.addEventListener("appinstalled", () => usePwaStore.setState({ prompt: null }));
  if (import.meta.env.PROD && "serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined); // SW hỏng không được chặn app
    });
  }
}

/** Mở hộp "Cài ứng dụng" của trình duyệt; trả true khi người dùng đồng ý. */
export async function installPwa(): Promise<boolean> {
  const e = usePwaStore.getState().prompt;
  if (!e) return false;
  await e.prompt();
  const { outcome } = await e.userChoice;
  usePwaStore.setState({ prompt: null });
  return outcome === "accepted";
}

/** Đang chạy như app (mở từ biểu tượng ngoài màn hình chính) — không cần hướng dẫn cài nữa. */
export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const ios = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return ios || window.matchMedia?.("(display-mode: standalone)").matches === true;
}

export type Platform = "ios" | "android" | "other";

/** Nền tảng để chọn sẵn tab hướng dẫn (iPad mới báo "Macintosh" nhưng có cảm ứng). */
export function platformOf(ua: string = navigator.userAgent, touchPoints: number = navigator.maxTouchPoints ?? 0): Platform {
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && touchPoints > 1)) return "ios";
  if (/Android/i.test(ua)) return "android";
  return "other";
}
