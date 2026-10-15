/** Thông báo đẩy của trình duyệt: đăng ký Web Push với khoá VAPID của máy chủ, gắn với tài khoản đang
 *  đăng nhập; tự gắn lại khi mở app nếu đã cho phép; gỡ khi đăng xuất. Service worker chỉ có ở bản build (`pwa.ts`). */
import { pushApi } from "@/features/push/api";

import { isStandalone, platformOf } from "./pwa";

export type PushState = "unsupported" | "needs-install" | "denied" | "off" | "on";

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return null;
  return (await navigator.serviceWorker.getRegistration()) ?? null;
}

function capable(): boolean {
  return typeof window !== "undefined" && "PushManager" in window && "Notification" in window;
}

/** Trạng thái trên máy này: iPhone / iPad chỉ nhận Web Push khi đã thêm vào màn hình chính (iOS 16.4+). */
export async function pushState(): Promise<PushState> {
  if (platformOf() === "ios" && !isStandalone()) return "needs-install";
  const reg = await registration();
  if (!capable() || !reg) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  if (Notification.permission !== "granted") return "off";
  return (await reg.pushManager.getSubscription()) ? "on" : "off";
}

function toInput(sub: PushSubscription) {
  const json = sub.toJSON();
  return {
    endpoint: sub.endpoint,
    keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" },
    user_agent: navigator.userAgent.slice(0, 300),
  };
}

async function subscribed(reg: ServiceWorkerRegistration, publicKey: string): Promise<PushSubscription> {
  const existing = await reg.pushManager.getSubscription();
  if (existing) return existing;
  return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) });
}

/** Bấm "Bật": xin quyền (cần thao tác của người dùng) → đăng ký → lưu ở máy chủ. Trả trạng thái mới. */
export async function enablePush(publicKey: string): Promise<PushState> {
  const reg = await registration();
  if (!capable() || !reg) return "unsupported";
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return perm === "denied" ? "denied" : "off";
  await pushApi.subscribe(toInput(await subscribed(reg, publicKey)));
  return "on";
}

/** Tắt trên máy này (cũng gọi khi đăng xuất) — lỗi mạng không chặn việc gỡ ở trình duyệt. */
export async function disablePush(): Promise<void> {
  const sub = await (await registration())?.pushManager.getSubscription();
  if (!sub) return;
  await pushApi.unsubscribe(sub.endpoint).catch(() => undefined);
  await sub.unsubscribe().catch(() => false);
}

/** Mở app khi quyền đã cấp → gắn (lại) đăng ký của máy với tài khoản đang đăng nhập. Không bao giờ ném. */
export async function syncPush(): Promise<void> {
  try {
    if (!capable() || Notification.permission !== "granted") return;
    const reg = await registration();
    if (!reg) return;
    const cfg = await pushApi.config();
    if (!cfg.enabled || !cfg.public_key) return;
    await pushApi.subscribe(toInput(await subscribed(reg, cfg.public_key)));
  } catch {
    // đồng bộ nền — lần mở app sau thử lại
  }
}
