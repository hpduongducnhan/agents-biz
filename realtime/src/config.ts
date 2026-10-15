/** Cấu hình service realtime từ biến môi trường (dùng chung file .env gốc repo với backend). */

import { isAbsolute, resolve } from "node:path";

export interface RealtimeConfig {
  rabbitUrl: string;
  publicKeyPath: string; // "" khi khoá lấy từ env
  publicKeyPem: string; // "" khi khoá lấy từ file
  algorithm: string;
  port: number;
  wsPath: string;
  logJson: boolean;
  logLevel: string;
  rateLimit: { events: number; windowMs: number };
  queueMax: number;
  messageTtlMs: number;
  expiryGraceMs: number; // token hết hạn mà không auth:refresh trong khoảng này → ngắt socket
}

type Env = Record<string, string | undefined>;

/** Giá trị .env có thể kèm comment cuối dòng (`8203   # cổng`) — bỏ phần comment. */
function clean(value: string | undefined): string {
  return (value ?? "").replace(/\s+#.*$/, "").trim();
}

function required(env: Env, name: string): string {
  const value = clean(env[name]);
  if (!value) throw new Error(`${name} chưa cấu hình`);
  return value;
}

function parseRate(value: string): { events: number; windowMs: number } {
  const m = /^(\d+)\/(\d+)(ms|s|m)$/.exec(value);
  if (!m) throw new Error(`REALTIME_RATE_LIMIT sai dạng "${value}" (vd 20/10s)`);
  const unit = { ms: 1, s: 1000, m: 60_000 }[m[3] as "ms" | "s" | "m"];
  return { events: Number(m[1]), windowMs: Number(m[2]) * unit };
}

/** PEM dán vào env có khi thành một dòng với `\\n`, có khi bị escape thêm thành `\\\\n` (Coolify) — đưa về
 * nhiều dòng. PEM không bao giờ chứa `\\` nên bỏ mọi `\\` còn sót. */
function pemFromEnv(value: string | undefined): string {
  return (value ?? "").trim().replace(/\\+n/g, "\n").replaceAll("\\", "");
}

export function loadConfig(env: Env, root: string): RealtimeConfig {
  const publicKeyPem = pemFromEnv(env.AUTH_PUBLIC_KEY);
  const keyFile = publicKeyPem ? "" : required(env, "AUTH_PUBLIC_KEY_FILE");
  const wsPath = (clean(env.WS_PATH) || clean(env.VITE_WS_PATH) || "/bizwithagents/ws").replace(/\/+$/, "");
  return {
    rabbitUrl: required(env, "RABBITMQ_URL"),
    publicKeyPath: !keyFile || isAbsolute(keyFile) ? keyFile : resolve(root, keyFile),
    publicKeyPem,
    algorithm: clean(env.AUTH_ALGORITHM) || "EdDSA",
    port: Number(clean(env.REALTIME_PORT) || 8203),
    wsPath,
    logJson: (clean(env.LOG_JSON) || "true").toLowerCase() !== "false",
    logLevel: (clean(env.LOG_LEVEL) || "INFO").toUpperCase(),
    rateLimit: parseRate(clean(env.REALTIME_RATE_LIMIT) || "20/10s"),
    queueMax: Number(clean(env.REALTIME_QUEUE_MAX) || 10_000),
    messageTtlMs: 30_000,
    expiryGraceMs: 30_000,
  };
}
