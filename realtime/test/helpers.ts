/** Hỗ trợ test: khoá / token Ed25519 tạm, vhost RabbitMQ test, khởi instance realtime, chờ event. */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { SignJWT, exportSPKI, generateKeyPair } from "jose";

export interface TestKeys {
  privateKey: CryptoKey;
  publicKeyPath: string;
}

export async function makeKeys(): Promise<TestKeys> {
  const { privateKey, publicKey } = await generateKeyPair("EdDSA", { extractable: true });
  const dir = mkdtempSync(join(tmpdir(), "rt-keys-"));
  const publicKeyPath = join(dir, "pub.pem");
  writeFileSync(publicKeyPath, await exportSPKI(publicKey));
  return { privateKey, publicKeyPath };
}

export interface ClaimsIn {
  sub: string;
  perms?: string[];
  sup?: boolean;
  tid?: string;
  typ?: string;
  ttlSeconds?: number;
  iat?: number; // giây epoch — mặc định bây giờ
}

export async function makeToken(keys: TestKeys, c: ClaimsIn): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({
    perms: c.perms ?? [],
    sup: c.sup ?? false,
    typ: c.typ ?? "access",
    ...(c.tid ? { tid: c.tid } : {}),
  })
    .setProtectedHeader({ alg: "EdDSA" })
    .setSubject(c.sub)
    .setIssuedAt(c.iat ?? now)
    .setExpirationTime(now + (c.ttlSeconds ?? 600))
    .sign(keys.privateKey);
}

/** URL RabbitMQ test: vhost của RABBITMQ_URL đổi thành `bizwithagents_test` (từ chối mọi vhost khác *_test). */
export function testRabbitUrl(): string {
  const base = process.env.RABBITMQ_URL;
  if (!base) throw new Error("RABBITMQ_URL chưa có (chạy test qua make rt-test để nạp .env)");
  const url = base.replace(/\s+#.*$/, "").trim().replace(/\/[^/]*$/, "/bizwithagents_test");
  if (!url.endsWith("_test")) throw new Error("test realtime chỉ chạy trên vhost *_test");
  return url;
}

export function waitFor<T>(fn: () => T | undefined | false, timeoutMs = 5000): Promise<T> {
  const started = Date.now();
  return new Promise((resolveP, reject) => {
    const tick = () => {
      const value = fn();
      if (value) return resolveP(value as T);
      if (Date.now() - started > timeoutMs) return reject(new Error("waitFor: hết giờ"));
      setTimeout(tick, 20);
    };
    tick();
  });
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ── Khởi realtime + client + publisher cho test e2e ──

import { type Channel, type ChannelModel, connect as amqpConnect } from "amqplib";
import { type Socket, io } from "socket.io-client";

import { type RealtimeConfig, loadConfig } from "../src/config.ts";
import { type RunningRealtime, startRealtime } from "../src/server.ts";
import { createLogger } from "../src/log.ts";

export const WS_PATH = "/ws";
const quiet = createLogger({ json: true, level: process.env.RT_TEST_LOG ?? "ERROR" });

export async function startTestRealtime(
  keys: TestKeys,
  env: Record<string, string> = {},
  overrides: Partial<RealtimeConfig> = {},
): Promise<RunningRealtime> {
  const config = loadConfig(
    { RABBITMQ_URL: testRabbitUrl(), AUTH_PUBLIC_KEY_FILE: keys.publicKeyPath, WS_PATH, ...env },
    "/",
  );
  return startRealtime({ ...config, port: 0, ...overrides }, quiet);
}

export function connectClient(rt: RunningRealtime, token: string): Promise<Socket> {
  return new Promise((resolveP, reject) => {
    const socket = io(`http://127.0.0.1:${rt.port}`, {
      path: `${WS_PATH}/socket.io/`,
      transports: ["websocket"],
      auth: { token },
      reconnection: false,
      forceNew: true,
    });
    socket.once("connect", () => resolveP(socket));
    socket.once("connect_error", (err) => {
      socket.close();
      reject(err);
    });
  });
}

export class Publisher {
  conn!: ChannelModel;
  ch!: Channel;

  async open(): Promise<this> {
    this.conn = await amqpConnect(testRabbitUrl());
    this.ch = await this.conn.createChannel();
    return this;
  }

  out(routingKey: string, event: string, data: unknown, cid = "cid-test"): void {
    const env = { v: 1, event, data, cid, ts: new Date().toISOString() };
    this.ch.publish("bw.rt.out", routingKey, Buffer.from(JSON.stringify(env)), { correlationId: cid });
  }

  /** Body tuỳ ý (JSON hỏng, envelope lạ…) — như một publisher lỗi. */
  raw(routingKey: string, body: string): void {
    this.ch.publish("bw.rt.out", routingKey, Buffer.from(body));
  }

  async close(): Promise<void> {
    await this.conn.close();
  }
}

/** Ghi lại mọi event client nhận được (tên, data, meta). */
export function record(socket: Socket): Array<{ event: string; data: unknown; meta: unknown }> {
  const got: Array<{ event: string; data: unknown; meta: unknown }> = [];
  socket.onAny((event, data, meta) => got.push({ event, data, meta }));
  return got;
}
