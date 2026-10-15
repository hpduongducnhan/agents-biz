/** Service realtime: HTTP (health / metrics) + Socket.IO + cầu RabbitMQ. Không logic nghiệp vụ, không DB. */

import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { Server, type Socket } from "socket.io";

import { AuthError, type Claims, importPublicKey, loadPublicKey, verifyAccess } from "./auth.ts";
import { BindingTable } from "./bindings.ts";
import type { RealtimeConfig } from "./config.ts";
import {
  CONTROL_PREFIX,
  ENVELOPE_VERSION,
  type OutEnvelope,
  inboundEnvelope,
  isClientEvent,
  isOutEvent,
  keysFor,
  roomFor,
} from "./envelope.ts";
import type { Logger } from "./log.ts";
import { type Delivery, RabbitBridge } from "./rabbit.ts";
import { TokenBucket } from "./ratelimit.ts";

export interface RealtimeStats {
  sockets: number;
  bindings: number;
  delivered: number;
  dropped: number;
  published: number;
  rejected: number;
}

export interface RunningRealtime {
  port: number;
  bindingKeys(): string[];
  rabbitConnected(): boolean;
  stats(): RealtimeStats;
  dropRabbitForTest(): Promise<void>;
  close(): Promise<void>;
}

interface SocketState {
  claims: Claims;
  keys: string[];
  bucket: TokenBucket;
  expired: boolean;
  timer?: NodeJS.Timeout;
}

type Ack = (reply: Record<string, unknown>) => void;

/** Tách ack (luôn là tham số cuối kiểu function) khỏi dữ liệu event. */
function splitAck(args: unknown[]): { data: unknown; ack: Ack } {
  const last = args.at(-1);
  if (typeof last === "function") return { data: args.length > 1 ? args[0] : null, ack: last as Ack };
  return { data: args[0] ?? null, ack: () => {} };
}

function roomsOf(keys: string[]): string[] {
  return keys.map((k) => roomFor(k)).flatMap((r) => (r && "room" in r ? [r.room] : []));
}

export async function startRealtime(config: RealtimeConfig, log: Logger): Promise<RunningRealtime> {
  const key = config.publicKeyPem
    ? await importPublicKey(config.publicKeyPem, config.algorithm)
    : await loadPublicKey(config.publicKeyPath, config.algorithm);
  const bindings = new BindingTable();
  const counters = { delivered: 0, dropped: 0, published: 0, rejected: 0 };
  const httpServer = createServer((req, res) => {
    const json = (status: number, body: unknown) =>
      res.writeHead(status, { "content-type": "application/json" }).end(JSON.stringify(body));
    const path = (req.url ?? "").split("?")[0];
    if (path === `${config.wsPath}/health`) {
      const ok = bridge.connected;
      return json(ok ? 200 : 503, { status: ok ? "ok" : "degraded", rabbit: ok, sockets: io.engine.clientsCount });
    }
    if (path === `${config.wsPath}/metrics`) {
      return json(200, { sockets: io.engine.clientsCount, bindings: bridge.boundKeys().length, ...counters });
    }
    return json(404, { error: "not found" });
  });
  const io = new Server(httpServer, { path: `${config.wsPath}/socket.io/`, transports: ["websocket"], serveClient: false });
  const bridge = new RabbitBridge(config.rabbitUrl, log, config, () => bindings.keys());

  /** Exception trong callback consume = amqplib đóng cả kết nối (mất mọi message đang đệm) → không để lọt ra. */
  function deliver(d: Delivery): void {
    try {
      route(d);
    } catch (err) {
      counters.dropped++;
      log.error(`chuyển message bw.rt.out lỗi: ${(err as Error).message}`, { loc: "ws2204", routing_key: d.routingKey });
    }
  }

  function route(d: Delivery): void {
    let env: OutEnvelope | null;
    try {
      env = JSON.parse(d.body.toString("utf8"));
    } catch {
      counters.dropped++;
      log.warn("message bw.rt.out không phải JSON — bỏ", { loc: "ws2201", routing_key: d.routingKey });
      return;
    }
    const target = roomFor(d.routingKey);
    if (typeof env !== "object" || env === null || env.v !== ENVELOPE_VERSION || typeof env.event !== "string" || !target) {
      counters.dropped++;
      log.warn("envelope không hỗ trợ — bỏ", { loc: "ws2202", routing_key: d.routingKey, v: env?.v, cid: env?.cid });
      return;
    }
    if (env.event.startsWith(CONTROL_PREFIX) || !isOutEvent(env.event)) {
      if (env.event === "rt:revoke") return revoke(env.data, env.cid ?? d.correlationId ?? null);
      counters.dropped++;
      log.warn("tên event ra không hợp lệ — bỏ", { loc: "ws2203", routing_key: d.routingKey, event: env.event, cid: env.cid });
      return;
    }
    const meta = { cid: env.cid ?? d.correlationId ?? null, ts: env.ts };
    if ("all" in target) io.emit(env.event, env.data, meta);
    else io.to(target.room).emit(env.event, env.data, meta);
    counters.delivered++;
  }

  /** sub → access token cấp từ `before` trở về trước bị từ chối, tới `until` (lúc token cũ nhất hết hạn). */
  const revoked = new Map<string, { before: number; until: number }>();

  function isRevoked(c: Claims): boolean {
    const r = revoked.get(c.sub);
    if (!r) return false;
    if (r.until * 1000 <= Date.now()) {
      revoked.delete(c.sub);
      return false;
    }
    return c.iat <= r.before;
  }

  /** Khoá tài khoản (backend gửi tới `all` → mọi instance): ngắt socket của user + nhớ mốc để chặn token cũ. */
  function revoke(data: unknown, cid: string | null): void {
    const d = data as { sub?: unknown; before?: unknown; until?: unknown } | null;
    if (typeof d?.sub !== "string" || typeof d.before !== "number" || typeof d.until !== "number") {
      counters.dropped++;
      log.warn("rt:revoke sai dạng — bỏ", { loc: "ws2203", cid });
      return;
    }
    const now = Date.now() / 1000;
    for (const [sub, r] of revoked) if (r.until <= now) revoked.delete(sub);
    revoked.set(d.sub, { before: d.before, until: d.until });
    io.in(`user:${d.sub}`).disconnectSockets(true);
    log.info("thu hồi phiên realtime của user", { loc: "ws2003", user: d.sub, cid });
  }

  /** Bảng đếm đổi đồng bộ (không await ở giữa) → binding RabbitMQ đuổi theo bằng một vòng tuần tự duy nhất. */
  function track(added: string[], removed: string[]): void {
    bindings.acquire(added);
    bindings.release(removed);
    void bridge.sync();
  }

  io.use(async (socket, next) => {
    const token = (socket.handshake.auth as { token?: unknown } | undefined)?.token;
    try {
      const claims = await verifyAccess(typeof token === "string" ? token : "", key, config.algorithm);
      if (isRevoked(claims)) throw new AuthError("revoked");
      (socket.data as SocketState).claims = claims;
      next();
    } catch (err) {
      counters.rejected++;
      log.info("từ chối handshake", { loc: "ws2401", reason: err instanceof AuthError ? err.message : String(err) });
      next(new Error("unauthorized"));
    }
  });

  function scheduleExpiry(socket: Socket, state: SocketState): void {
    clearTimeout(state.timer);
    state.expired = false;
    state.timer = setTimeout(
      () => {
        state.expired = true;
        socket.emit("auth:expired");
        // Không làm mới kịp → ngắt: room cũ (quyền superadmin đã mất) không được nghe mãi.
        state.timer = setTimeout(() => {
          log.info("token hết hạn không làm mới — ngắt socket", { loc: "ws2005", user: state.claims.sub });
          socket.disconnect(true);
        }, config.expiryGraceMs);
        state.timer.unref();
      },
      Math.max(0, state.claims.exp * 1000 - Date.now()),
    );
    state.timer.unref();
  }

  async function refresh(socket: Socket, state: SocketState, payload: unknown, ack: Ack): Promise<void> {
    const token = (payload as { token?: unknown } | null)?.token;
    let claims: Claims;
    try {
      claims = await verifyAccess(typeof token === "string" ? token : "", key, config.algorithm);
    } catch {
      ack({ ok: false, error: "unauthorized" });
      return;
    }
    if (!socket.connected) return; // rời trong lúc kiểm token: disconnect đã trả key cũ
    if (isRevoked(claims)) {
      ack({ ok: false, error: "unauthorized" });
      return;
    }
    if (claims.sub !== state.claims.sub) {
      log.warn("auth:refresh bằng token của user khác — từ chối", { loc: "ws2403", user: state.claims.sub });
      ack({ ok: false, error: "user_mismatch" });
      return;
    }
    const before = state.keys;
    const after = keysFor(claims);
    const added = after.filter((k) => !before.includes(k));
    const removed = before.filter((k) => !after.includes(k));
    for (const room of roomsOf(removed)) socket.leave(room);
    for (const room of roomsOf(added)) socket.join(room);
    state.claims = claims;
    state.keys = after;
    scheduleExpiry(socket, state);
    track(added, removed);
    ack({ ok: true });
  }

  function inbound(socket: Socket, state: SocketState, event: string, data: unknown, ack: Ack): void {
    const reject = (error: string) => {
      counters.rejected++;
      ack({ accepted: false, error });
    };
    if (!isClientEvent(event)) return reject("invalid_event");
    if (state.expired || state.claims.exp * 1000 <= Date.now()) {
      socket.emit("auth:expired");
      return reject("token_expired");
    }
    if (!state.bucket.take()) {
      log.warn("event client vượt rate limit", { loc: "ws2402", user: state.claims.sub, event });
      return reject("rate_limited");
    }
    const cid = randomUUID().replaceAll("-", "");
    if (!bridge.publishIn(event, inboundEnvelope(event, data, state.claims, socket.id, cid), cid)) {
      return reject("unavailable");
    }
    counters.published++;
    ack({ accepted: true, cid });
  }

  io.on("connection", (socket: Socket) => {
    const state = socket.data as SocketState;
    state.keys = keysFor(state.claims);
    state.bucket = new TokenBucket(config.rateLimit.events, config.rateLimit.windowMs);
    for (const room of roomsOf(state.keys)) socket.join(room);
    scheduleExpiry(socket, state);
    socket.on("auth:refresh", (...args: unknown[]) => {
      const { data, ack } = splitAck(args);
      void refresh(socket, state, data, ack);
    });
    socket.onAny((event: string, ...args: unknown[]) => {
      if (event === "auth:refresh") return;
      const { data, ack } = splitAck(args);
      inbound(socket, state, event, data, ack);
    });
    socket.on("disconnect", () => {
      clearTimeout(state.timer);
      track([], state.keys);
    });
    track(state.keys, []);
    log.debug("socket nối", { loc: "ws2004", user: state.claims.sub });
  });

  await bridge.start(deliver);
  await new Promise<void>((resolveP) => httpServer.listen(config.port, resolveP));
  const port = (httpServer.address() as AddressInfo).port;
  log.info("realtime sẵn sàng", { loc: "ws2001", port, path: `${config.wsPath}/socket.io/` });

  return {
    port,
    bindingKeys: () => bridge.boundKeys(),
    rabbitConnected: () => bridge.connected,
    stats: () => ({ sockets: io.engine.clientsCount, bindings: bindings.size, ...counters }),
    dropRabbitForTest: () => bridge.dropForTest(),
    close: async () => {
      await io.close();
      await bridge.close();
      log.info("realtime đã dừng", { loc: "ws2002" });
    },
  };
}
