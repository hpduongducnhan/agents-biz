/**
 * Một socket duy nhất tới service realtime — app cấu hình + mở; trang chỉ nghe / gửi qua hook.
 * Token đọc lại mỗi lần bắt tay (auth là hàm) → reconnect luôn dùng token hiện tại.
 */
import { type Socket, io } from "socket.io-client";
import { create } from "zustand";

import { refreshSession } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth-tokens";

export type RealtimeMeta = { cid?: string | null; ts?: string };
export type RealtimeHandler = (data: unknown, meta?: RealtimeMeta) => void;
export type SendAck = { accepted: boolean; cid?: string; error?: string };
export type SocketStatus = "connected" | "connecting" | "offline";

export const useSocketStatusStore = create<{ status: SocketStatus }>(() => ({ status: "offline" }));

type Options = { url: string; path: string; onReconnect?: () => void };

const MAX_RECOVER = 3; // bị từ chối liên tục (sai cấu hình khoá…) → thôi, tránh vòng lặp refresh

class SocketManager {
  private socket: Socket | null = null;
  private options: Options | null = null;
  private readonly handlers = new Map<string, Set<RealtimeHandler>>();
  private failures = 0;
  private recovering = false;
  private connectedOnce = false;

  configure(options: Options): void {
    this.options = options;
  }

  connect(): void {
    if (this.socket || !this.options || !getAccessToken()) return;
    const socket = io(this.options.url, {
      path: this.options.path,
      transports: ["websocket"],
      auth: (cb) => cb({ token: getAccessToken() }),
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30_000,
    });
    this.failures = 0;
    this.connectedOnce = false;
    useSocketStatusStore.setState({ status: "connecting" });
    socket.on("connect", () => {
      this.failures = 0;
      useSocketStatusStore.setState({ status: "connected" });
      if (this.connectedOnce) this.options?.onReconnect?.(); // nối lại: dữ liệu có thể đã cũ trong lúc mất kết nối
      this.connectedOnce = true;
    });
    socket.on("disconnect", (reason: string) => {
      useSocketStatusStore.setState({ status: "connecting" });
      if (reason === "io server disconnect") void this.recover(socket); // bị ngắt: token hết hạn / bị thu hồi
    });
    socket.on("connect_error", () => {
      useSocketStatusStore.setState({ status: "offline" });
      if (!socket.active) void this.recover(socket); // bị từ chối lúc bắt tay: socket.io không tự thử lại
    });
    socket.onAny((event: string, data: unknown, meta?: RealtimeMeta) => {
      for (const h of this.handlers.get(event) ?? []) h(data, meta);
    });
    this.socket = socket;
  }

  disconnect(): void {
    this.socket?.removeAllListeners();
    this.socket?.disconnect();
    this.socket = null;
    useSocketStatusStore.setState({ status: "offline" });
  }

  on(event: string, handler: RealtimeHandler): () => void {
    let set = this.handlers.get(event);
    if (!set) this.handlers.set(event, (set = new Set()));
    set.add(handler);
    return () => set.delete(handler);
  }

  send(event: string, data?: unknown): Promise<SendAck> {
    const socket = this.socket;
    if (!socket) return Promise.resolve({ accepted: false, error: "offline" });
    return new Promise((resolve) =>
      socket.timeout(5000).emit(event, data ?? null, (err: Error | null, ack: SendAck) =>
        resolve(err ? { accepted: false, error: "timeout" } : ack),
      ),
    );
  }

  /** Làm mới phiên rồi nối lại. Refresh hỏng = phiên đã hết (http tự đăng xuất) → để yên. */
  private async recover(socket: Socket): Promise<void> {
    if (this.recovering || this.failures >= MAX_RECOVER) return;
    this.recovering = true;
    this.failures++;
    try {
      await refreshSession();
    } catch {
      return;
    } finally {
      this.recovering = false;
    }
    if (this.socket === socket) socket.connect();
  }

  /** Token mới (refresh single-flight) → báo service realtime đổi claims / room không cần nối lại. */
  async refreshAuth(): Promise<void> {
    const token = await refreshSession();
    await new Promise<void>((resolve) =>
      this.socket ? this.socket.timeout(5000).emit("auth:refresh", { token }, () => resolve()) : resolve(),
    );
  }
}

export const socketManager = new SocketManager();
