// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { disablePush, enablePush, pushState, syncPush } from "@/lib/push";

vi.mock("@/features/push/api", () => ({
  pushApi: { config: vi.fn(), subscribe: vi.fn().mockResolvedValue({ id: "s1" }), unsubscribe: vi.fn().mockResolvedValue({ removed: 1 }) },
}));
const { pushApi } = await import("@/features/push/api");

const KEY = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4";
const sub = (endpoint = "https://fcm.googleapis.com/x") => ({
  endpoint,
  toJSON: () => ({ keys: { p256dh: "P", auth: "A" } }),
  unsubscribe: vi.fn().mockResolvedValue(true),
});

type Sub = ReturnType<typeof sub>;
const manager = { getSubscription: vi.fn<() => Promise<Sub | null>>(), subscribe: vi.fn() };
const original = { sw: Object.getOwnPropertyDescriptor(navigator, "serviceWorker"), ua: navigator.userAgent };

function env(opts: { sw?: boolean; push?: boolean; permission?: NotificationPermission; request?: NotificationPermission; ua?: string }) {
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: opts.sw === false ? undefined : { getRegistration: vi.fn().mockResolvedValue({ pushManager: manager }) },
  });
  if (opts.sw === false) delete (navigator as unknown as Record<string, unknown>).serviceWorker;
  if (opts.push === false) delete (window as unknown as Record<string, unknown>).PushManager;
  else (window as unknown as Record<string, unknown>).PushManager = class {};
  (window as unknown as Record<string, unknown>).Notification = Object.assign(vi.fn(), {
    permission: opts.permission ?? "default",
    requestPermission: vi.fn().mockResolvedValue(opts.request ?? "granted"),
  });
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: opts.ua ?? "Mozilla/5.0 (X11; Linux) Chrome" });
}

beforeEach(() => {
  vi.clearAllMocks();
  manager.getSubscription.mockResolvedValue(null);
  vi.mocked(pushApi.subscribe).mockResolvedValue({ id: "s1" } as never);
  vi.mocked(pushApi.unsubscribe).mockResolvedValue({ removed: 1 } as never);
  window.matchMedia = (() => ({ matches: false })) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  if (original.sw) Object.defineProperty(navigator, "serviceWorker", original.sw);
  else delete (navigator as unknown as Record<string, unknown>).serviceWorker;
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: original.ua });
});

describe("pushState", () => {
  it("iPhone chưa thêm vào màn hình chính → needs-install, kể cả khi có API", async () => {
    env({ ua: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)" });
    expect(await pushState()).toBe("needs-install");
  });
  it("iPhone đã chạy như app → xét như bình thường", async () => {
    env({ ua: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)" });
    window.matchMedia = ((q: string) => ({ matches: q.includes("standalone") })) as unknown as typeof window.matchMedia;
    expect(await pushState()).toBe("off");
  });
  it("không có service worker / PushManager → unsupported", async () => {
    env({ sw: false });
    expect(await pushState()).toBe("unsupported");
    env({ push: false });
    expect(await pushState()).toBe("unsupported");
  });
  it("chưa đăng ký service worker → unsupported", async () => {
    env({});
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { getRegistration: vi.fn().mockResolvedValue(undefined) } });
    expect(await pushState()).toBe("unsupported");
  });
  it("quyền denied / default / granted không có đăng ký / granted có đăng ký", async () => {
    env({ permission: "denied" });
    expect(await pushState()).toBe("denied");
    env({ permission: "default" });
    expect(await pushState()).toBe("off");
    env({ permission: "granted" });
    expect(await pushState()).toBe("off");
    manager.getSubscription.mockResolvedValue(sub());
    expect(await pushState()).toBe("on");
  });
});

describe("enablePush", () => {
  it("cấp quyền → subscribe với applicationServerKey (65 byte) → lưu ở máy chủ → on", async () => {
    env({});
    const s = sub();
    manager.subscribe.mockResolvedValue(s);
    expect(await enablePush(KEY)).toBe("on");
    const arg = manager.subscribe.mock.calls[0]![0];
    expect(arg.userVisibleOnly).toBe(true);
    expect(arg.applicationServerKey).toBeInstanceOf(Uint8Array);
    expect(arg.applicationServerKey).toHaveLength(65);
    expect(arg.applicationServerKey[0]).toBe(4);
    expect(pushApi.subscribe).toHaveBeenCalledWith({
      endpoint: s.endpoint,
      keys: { p256dh: "P", auth: "A" },
      user_agent: expect.stringContaining("Chrome"),
    });
  });
  it("đã có đăng ký trình duyệt → dùng lại, không subscribe lần nữa", async () => {
    env({});
    manager.getSubscription.mockResolvedValue(sub());
    await enablePush(KEY);
    expect(manager.subscribe).not.toHaveBeenCalled();
    expect(pushApi.subscribe).toHaveBeenCalledOnce();
  });
  it("người dùng từ chối → denied; bỏ qua hộp thoại → off; không gọi máy chủ", async () => {
    env({ request: "denied" });
    expect(await enablePush(KEY)).toBe("denied");
    env({ request: "default" });
    expect(await enablePush(KEY)).toBe("off");
    expect(pushApi.subscribe).not.toHaveBeenCalled();
  });
  it("trình duyệt không hỗ trợ → unsupported", async () => {
    env({ push: false });
    expect(await enablePush(KEY)).toBe("unsupported");
  });
  it("máy chủ lỗi → ném lỗi cho giao diện hiện toast", async () => {
    env({});
    manager.subscribe.mockResolvedValue(sub());
    vi.mocked(pushApi.subscribe).mockRejectedValue(new Error("409"));
    await expect(enablePush(KEY)).rejects.toThrow("409");
  });
  it("thiếu keys trong toJSON → gửi chuỗi rỗng (máy chủ từ chối 422)", async () => {
    env({});
    manager.subscribe.mockResolvedValue({ endpoint: "https://fcm.googleapis.com/y", toJSON: () => ({}) });
    await enablePush(KEY);
    expect(vi.mocked(pushApi.subscribe).mock.calls[0]![0].keys).toEqual({ p256dh: "", auth: "" });
  });
});

describe("disablePush", () => {
  it("gỡ ở máy chủ rồi ở trình duyệt", async () => {
    env({});
    const s = sub();
    manager.getSubscription.mockResolvedValue(s);
    await disablePush();
    expect(pushApi.unsubscribe).toHaveBeenCalledWith(s.endpoint);
    expect(s.unsubscribe).toHaveBeenCalledOnce();
  });
  it("máy chủ lỗi vẫn gỡ ở trình duyệt, không ném", async () => {
    env({});
    const s = sub();
    manager.getSubscription.mockResolvedValue(s);
    vi.mocked(pushApi.unsubscribe).mockRejectedValue(new Error("net"));
    await expect(disablePush()).resolves.toBeUndefined();
    expect(s.unsubscribe).toHaveBeenCalledOnce();
  });
  it("chưa đăng ký / không có service worker → không gọi gì, không lỗi", async () => {
    env({});
    await disablePush();
    env({ sw: false });
    await disablePush();
    expect(pushApi.unsubscribe).not.toHaveBeenCalled();
  });
});

describe("syncPush", () => {
  it("quyền đã cấp + máy chủ bật → subscribe lại với đúng khoá", async () => {
    env({ permission: "granted" });
    vi.mocked(pushApi.config).mockResolvedValue({ enabled: true, public_key: KEY });
    manager.subscribe.mockResolvedValue(sub());
    await syncPush();
    expect(pushApi.subscribe).toHaveBeenCalledOnce();
  });
  it("quyền chưa cấp / máy chủ tắt / thiếu khoá / không hỗ trợ → không làm gì", async () => {
    env({ permission: "default" });
    await syncPush();
    env({ permission: "granted" });
    vi.mocked(pushApi.config).mockResolvedValue({ enabled: false, public_key: null });
    await syncPush();
    vi.mocked(pushApi.config).mockResolvedValue({ enabled: true, public_key: null });
    await syncPush();
    env({ permission: "granted", push: false });
    await syncPush();
    env({ permission: "granted", sw: false });
    await syncPush();
    expect(pushApi.subscribe).not.toHaveBeenCalled();
  });
  it("không bao giờ ném (config lỗi)", async () => {
    env({ permission: "granted" });
    vi.mocked(pushApi.config).mockRejectedValue(new Error("down"));
    await expect(syncPush()).resolves.toBeUndefined();
  });
});
