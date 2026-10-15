// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (...args: unknown[]) => void;
class FakeSocket {
  handlers = new Map<string, Handler>();
  any: Handler | null = null;
  emitted: unknown[][] = [];
  ack: unknown = { accepted: true, cid: "c1" };
  active = true; // false = service realtime từ chối bắt tay → socket.io không tự thử lại
  connectCalls = 0;
  connect() {
    this.connectCalls++;
  }
  on(event: string, h: Handler) {
    this.handlers.set(event, h);
    return this;
  }
  onAny(h: Handler) {
    this.any = h;
  }
  timeout() {
    return {
      emit: (event: string, data: unknown, cb: (err: Error | null, ack: unknown) => void) => (
        this.emitted.push([event, data]), cb(null, this.ack)
      ),
    };
  }
  removeAllListeners() {}
  disconnect() {}
}

const created: { url: string; opts: { auth: (cb: (a: unknown) => void) => void; path: string; transports: string[] }; socket: FakeSocket }[] = [];
vi.mock("socket.io-client", () => ({
  io: (url: string, opts: never) => {
    const socket = new FakeSocket();
    created.push({ url, opts, socket });
    return socket;
  },
}));
vi.mock("@/lib/api/client", async (orig) => ({ ...(await orig<object>()), refreshSession: vi.fn(async () => "fresh-token") }));

const { socketManager, useSocketStatusStore } = await import("@/lib/realtime/socket");
const { refreshSession } = await import("@/lib/api/client");
const { clearTokens, setTokens } = await import("@/lib/auth-tokens");
const flush = () => new Promise((r) => setTimeout(r, 0));
const PATH = "/bizwithagents/ws/socket.io/";

function first() {
  const c = created[0];
  if (!c) throw new Error("chưa mở socket");
  return c;
}

describe("socketManager", () => {
  beforeEach(() => {
    created.length = 0;
    socketManager.configure({ url: "http://h", path: PATH });
  });
  afterEach(() => {
    socketManager.disconnect();
    clearTokens();
    vi.mocked(refreshSession).mockClear();
  });

  it("không có token thì không nối; có token → chỉ websocket, bắt tay đọc token lúc kết nối", () => {
    socketManager.connect();
    expect(created).toHaveLength(0);
    setTokens("t1", "r1");
    socketManager.connect();
    socketManager.connect(); // gọi lại: không mở socket thứ hai
    expect(created).toHaveLength(1);
    expect(first().opts.path).toBe(PATH);
    expect(first().opts.transports).toEqual(["websocket"]);
    setTokens("t2", "r2"); // reconnect sau này dùng token mới nhất
    let auth: unknown;
    first().opts.auth((a) => (auth = a));
    expect(auth).toEqual({ token: "t2" });
  });

  it("phát event tới handler đã đăng ký; huỷ đăng ký thì thôi nhận", () => {
    setTokens("t", "r");
    socketManager.connect();
    const seen: unknown[] = [];
    const off = socketManager.on("core:notification", (data, meta) => seen.push([data, meta]));
    first().socket.any?.("core:notification", { id: 1 }, { cid: "x" });
    off();
    first().socket.any?.("core:notification", { id: 2 });
    expect(seen).toEqual([[{ id: 1 }, { cid: "x" }]]);
  });

  it("trạng thái kết nối đi theo sự kiện socket", () => {
    setTokens("t", "r");
    socketManager.connect();
    expect(useSocketStatusStore.getState().status).toBe("connecting");
    first().socket.handlers.get("connect")?.();
    expect(useSocketStatusStore.getState().status).toBe("connected");
    first().socket.handlers.get("connect_error")?.();
    expect(useSocketStatusStore.getState().status).toBe("offline");
  });

  it("send: offline → không gửi; online → trả ack", async () => {
    expect(await socketManager.send("notifications.mark_read", { ids: ["n1"] })).toEqual({ accepted: false, error: "offline" });
    setTokens("t", "r");
    socketManager.connect();
    expect(await socketManager.send("notifications.mark_read", { ids: ["n1"] })).toEqual({ accepted: true, cid: "c1" });
    expect(first().socket.emitted).toEqual([["notifications.mark_read", { ids: ["n1"] }]]);
  });

  it("refreshAuth: refresh token rồi báo service realtime token mới", async () => {
    setTokens("t", "r");
    socketManager.connect();
    await socketManager.refreshAuth();
    expect(first().socket.emitted).toEqual([["auth:refresh", { token: "fresh-token" }]]);
  });

  it("bị service realtime ngắt (thu hồi) → làm mới phiên rồi nối lại; rớt mạng thường → để socket.io tự lo", async () => {
    setTokens("t", "r");
    socketManager.connect();
    const fake = first().socket;
    fake.handlers.get("disconnect")?.("io server disconnect");
    await flush();
    expect(fake.connectCalls).toBe(1);
    fake.handlers.get("disconnect")?.("transport close");
    await flush();
    expect(refreshSession).toHaveBeenCalledTimes(1);
  });

  it("refresh hỏng (phiên đã bị thu hồi) → thôi, không nối lại", async () => {
    vi.mocked(refreshSession).mockRejectedValueOnce(new Error("401"));
    setTokens("t", "r");
    socketManager.connect();
    const fake = first().socket;
    fake.active = false;
    fake.handlers.get("connect_error")?.(new Error("unauthorized"));
    await flush();
    expect(fake.connectCalls).toBe(0);
    expect(useSocketStatusStore.getState().status).toBe("offline");
  });

  it("bị từ chối liên tục → dừng sau 3 lần; nối được thì đếm lại", async () => {
    setTokens("t", "r");
    socketManager.connect();
    const fake = first().socket;
    fake.active = false;
    for (let i = 0; i < 5; i++) {
      fake.handlers.get("connect_error")?.(new Error("unauthorized"));
      await flush();
    }
    expect(fake.connectCalls).toBe(3);
    fake.handlers.get("connect")?.();
    fake.handlers.get("connect_error")?.(new Error("unauthorized"));
    await flush();
    expect(fake.connectCalls).toBe(4);
  });

  it("ngủ máy lâu: rớt mạng → bắt tay lại bị từ chối (token hết hạn) → refresh 1 lần → nối lại → refetch", async () => {
    const onReconnect = vi.fn();
    socketManager.configure({ url: "http://h", path: PATH, onReconnect });
    setTokens("t", "r");
    socketManager.connect();
    const fake = first().socket;
    fake.handlers.get("connect")?.(); // lần nối đầu: không refetch
    expect(onReconnect).not.toHaveBeenCalled();
    fake.handlers.get("disconnect")?.("transport close"); // máy ngủ
    await flush();
    expect(refreshSession).not.toHaveBeenCalled();
    fake.active = false; // thức dậy: token cũ hết hạn → bị từ chối lúc bắt tay
    fake.handlers.get("connect_error")?.(new Error("unauthorized"));
    await flush();
    expect(refreshSession).toHaveBeenCalledTimes(1);
    expect(fake.connectCalls).toBe(1);
    fake.handlers.get("connect")?.();
    expect(onReconnect).toHaveBeenCalledTimes(1);
    expect(useSocketStatusStore.getState().status).toBe("connected");
  });

  it("nối lại sau rớt mạng thường → gọi onReconnect; mở socket mới (đăng nhập lại) thì đếm lại từ đầu", () => {
    const onReconnect = vi.fn();
    socketManager.configure({ url: "http://h", path: PATH, onReconnect });
    setTokens("t", "r");
    socketManager.connect();
    first().socket.handlers.get("connect")?.();
    first().socket.handlers.get("connect")?.();
    expect(onReconnect).toHaveBeenCalledTimes(1);
    socketManager.disconnect();
    socketManager.connect();
    created[1]?.socket.handlers.get("connect")?.();
    expect(onReconnect).toHaveBeenCalledTimes(1);
  });
});
