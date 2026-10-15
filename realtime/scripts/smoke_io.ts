/** I/O của smoke đầu-cuối: gọi API qua cửa web, bắt tay socket.io, chờ sự kiện, thăm dò. */

import { io, type Socket } from "socket.io-client";

import { classifyConnectError } from "./smoke_lib.ts";

export type Body = { success?: boolean; code?: number; data?: any; correlation_id?: string } | null;

export interface Reply {
  status: number;
  body: Body;
}

export interface CallOptions {
  body?: unknown;
  token?: string;
  ip?: string;
}

export function expect(ok: unknown, what: string): asserts ok {
  if (!ok) throw new Error(what);
}

export function dump(r: Reply): string {
  return `HTTP ${r.status} ${JSON.stringify(r.body).slice(0, 300)}`;
}

export function okData(r: Reply, what: string): any {
  expect(r.status === 200 && r.body?.success === true, `${what} → ${dump(r)}`);
  return r.body?.data;
}

export function need<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`thiếu ${what} — bước trước chưa chạy`);
  return value;
}

export async function poll(what: string, ms: number, fn: () => Promise<boolean>): Promise<void> {
  const until = Date.now() + ms;
  let last = "";
  while (Date.now() < until) {
    try {
      if (await fn()) return;
    } catch (err) {
      last = (err as Error).message;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`${what} sau ${ms / 1000}s${last ? ` — lỗi cuối: ${last}` : ""}`);
}

export class SocketRefused extends Error {
  kind: "auth" | "transport";
  constructor(message: string, kind: "auth" | "transport") {
    super(message);
    this.kind = kind;
  }
}

export function waitEvent(socket: Socket, events: string[], ms = 8000): Promise<{ event: string; data: unknown }> {
  return new Promise((resolve, reject) => {
    const handlers = new Map<string, (data: unknown) => void>();
    const cleanup = (): void => {
      clearTimeout(timer);
      for (const [event, h] of handlers) socket.off(event, h);
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error(`không nhận được ${events.join(" / ")} sau ${ms}ms`));
    }, ms);
    for (const event of events) {
      const h = (data: unknown): void => {
        cleanup();
        resolve({ event, data });
      };
      handlers.set(event, h);
      socket.on(event, h);
    }
  });
}

export interface Door {
  wsBase: string;
  call(method: "GET" | "POST", path: string, o?: CallOptions): Promise<Reply>;
  connect(token: string): Promise<Socket>;
  expectRefused(token: string): Promise<void>;
  bindingCount(): Promise<number>;
}

export function door(base: string, servicePath: string): Door {
  const api = `${base}/${servicePath}/api`;
  const wsBase = `${base}/${servicePath}/ws`;

  async function call(method: "GET" | "POST", path: string, o: CallOptions = {}): Promise<Reply> {
    const headers: Record<string, string> = { accept: "application/json" };
    if (o.body !== undefined) headers["content-type"] = "application/json";
    if (o.token) headers.authorization = `Bearer ${o.token}`;
    if (o.ip) {
      headers["cf-connecting-ip"] = o.ip; // nginx (docker / prod) lấy IP thật từ header này
      headers["x-forwarded-for"] = o.ip; // proxy Vite (local) chuyển nguyên, uvicorn tin 127.0.0.1
    }
    const r = await fetch(`${api}${path}`, {
      method,
      headers,
      body: o.body === undefined ? undefined : JSON.stringify(o.body),
    });
    return { status: r.status, body: (await r.json().catch(() => null)) as Body };
  }

  function connect(token: string): Promise<Socket> {
    const socket = io(base, {
      path: `/${servicePath}/ws/socket.io/`,
      transports: ["websocket"],
      auth: { token },
      reconnection: false,
      timeout: 8000,
    });
    return new Promise((resolve, reject) => {
      socket.once("connect", () => resolve(socket));
      socket.once("connect_error", (err: Error) => {
        socket.close();
        const kind = classifyConnectError(err.message);
        reject(new SocketRefused(`bắt tay socket lỗi (${kind}): ${err.message}`, kind));
      });
    });
  }

  async function expectRefused(token: string): Promise<void> {
    let socket: Socket | null = null;
    try {
      socket = await connect(token);
    } catch (err) {
      expect(
        err instanceof SocketRefused && err.kind === "auth",
        `${(err as Error).message} — mong đợi server từ chối "unauthorized"; lỗi transport = proxy / Cloudflare chặn websocket`,
      );
      return;
    }
    socket?.close();
    throw new Error("socket với token sai / đã thu hồi vẫn bắt tay được");
  }

  async function bindingCount(): Promise<number> {
    const r = await fetch(`${wsBase}/metrics`);
    const m = (await r.json().catch(() => null)) as { bindings?: unknown } | null;
    expect(r.status === 200 && typeof m?.bindings === "number", `${wsBase}/metrics → HTTP ${r.status}`);
    return m?.bindings as number;
  }

  return { wsBase, call, connect, expectRefused, bindingCount };
}
