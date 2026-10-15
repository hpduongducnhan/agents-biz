/** Phần thuần của smoke đầu-cuối (không I/O): tham số + chặn ghi prod, IP giả, phiên từ JWT, cache bundle, phiên bản. */

import { randomBytes } from "node:crypto";

export type Profile = "local" | "docker" | "prod";
export type MongoMode = "on" | "off";

export interface Credentials {
  email: string;
  password: string;
}

export interface Options {
  base: string;
  profile: Profile;
  expectMongo: MongoMode;
  admin: Credentials | null;
  prodLogin: Credentials | null;
  expectVersion: string | null;
  rateLimitOnProd: boolean;
  runId: string;
}

export interface Session {
  access: string;
  refresh: string;
  sub: string;
  sup: boolean;
  perms: string[];
}

export interface AssetCheck {
  path: string;
  status: number;
  cacheControl: string | null;
}

type Env = Record<string, string | undefined>;

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const DOCKER_ADMIN: Credentials = { email: "root@smoke.test", password: "smoke-password-1" };

export function parseOptions(argv: string[], env: Env): Options {
  const base = (argv[0] ?? "").replace(/\/+$/, "");
  if (!/^https?:\/\//.test(base)) throw new Error("thiếu URL gốc, vd http://127.0.0.1:8201");
  const at = argv.indexOf("--profile");
  const profile = at >= 0 ? argv[at + 1] : undefined;
  if (profile !== "local" && profile !== "docker" && profile !== "prod") {
    throw new Error("--profile phải là local | docker | prod");
  }
  const host = new URL(base).hostname;
  if (profile !== "prod" && !LOCAL_HOSTS.has(host)) {
    throw new Error(`profile ${profile} có ghi dữ liệu — chỉ chạy với máy local, không chạy với ${host}`);
  }
  const mongo = env.SMOKE_EXPECT_MONGO ?? (profile === "prod" ? "on" : undefined);
  if (mongo !== "on" && mongo !== "off") {
    throw new Error("đặt SMOKE_EXPECT_MONGO=on|off khớp chế độ của stack đang chạy");
  }
  const email = env.SMOKE_EMAIL;
  const password = env.SMOKE_PASSWORD;
  if (Boolean(email) !== Boolean(password)) throw new Error("SMOKE_EMAIL và SMOKE_PASSWORD phải đặt cùng nhau");
  let admin: Credentials | null = null;
  if (profile === "local") {
    admin = {
      email: env.SMOKE_ADMIN_EMAIL ?? "superadmin@test.local",
      password: env.SMOKE_ADMIN_PASSWORD ?? env.SEED_PASSWORD ?? "password123",
    };
  } else if (profile === "docker") {
    admin = DOCKER_ADMIN;
  }
  return {
    base,
    profile,
    expectMongo: mongo,
    admin,
    prodLogin: profile === "prod" && email && password ? { email, password } : null,
    expectVersion: env.SMOKE_EXPECT_VERSION || null,
    rateLimitOnProd: env.SMOKE_RATE_LIMIT === "1",
    runId: env.SMOKE_RUN_ID || randomBytes(3).toString("hex"),
  };
}

export function rateLimitEnabled(o: Pick<Options, "profile" | "rateLimitOnProd">): boolean {
  return o.profile !== "prod" || o.rateLimitOnProd;
}

export function fakeIp(runId: string, slot: number): string {
  const seed = Number.parseInt(runId.slice(0, 4), 16) || 0;
  return `203.0.113.${((seed + slot) % 254) + 1}`;
}

export function decodeJwt(token: string): Record<string, unknown> {
  const part = token.split(".")[1];
  if (!part) throw new Error("access token không phải JWT");
  return JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as Record<string, unknown>;
}

export function sessionFrom(data: unknown): Session {
  const d = (data ?? {}) as Record<string, unknown>;
  const t = (d.tokens ?? d) as Record<string, unknown>;
  const access = t.access_token;
  const refresh = t.refresh_token;
  if (typeof access !== "string" || typeof refresh !== "string") {
    throw new Error(`phản hồi thiếu access_token / refresh_token: ${JSON.stringify(data ?? null).slice(0, 200)}`);
  }
  const c = decodeJwt(access);
  return {
    access,
    refresh,
    sub: String(c.sub),
    sup: c.sup === true,
    perms: Array.isArray(c.perms) ? c.perms.map(String) : [],
  };
}

export function assetPaths(html: string): string[] {
  const out = new Set<string>();
  for (const m of html.matchAll(/(?:src|href)="(\/assets\/[^"]+\.(?:js|css))"/g)) {
    if (m[1]) out.add(m[1]);
  }
  return [...out];
}

export function isDevServer(html: string): boolean {
  return html.includes("/@vite/client");
}

export function cacheProblems(
  index: { cacheControl: string | null; cfCacheStatus: string | null },
  assets: AssetCheck[],
): string[] {
  const out: string[] = [];
  if (index.cacheControl !== "no-cache") {
    out.push(`index.html Cache-Control="${index.cacheControl}" (phải "no-cache" để thấy bản build mới)`);
  }
  if (index.cfCacheStatus?.toUpperCase() === "HIT") {
    out.push("Cloudflare đang cache index.html (cf-cache-status: HIT) — bỏ quy tắc cache HTML");
  }
  if (assets.length === 0) out.push("index.html không trỏ tới asset /assets/*.js|css nào");
  for (const a of assets) {
    if (a.status !== 200) out.push(`${a.path} → HTTP ${a.status} (index.html cũ trỏ tới asset đã mất?)`);
    else if (!a.cacheControl?.includes("immutable")) out.push(`${a.path} thiếu Cache-Control immutable`);
  }
  return out;
}

export function mongoMode(ready: Record<string, unknown>): MongoMode {
  if (ready.mongo === "disabled") return "off";
  if (ready["mongo.rw"] === "ok") return "on";
  throw new Error(`health/ready không cho biết chế độ Mongo: ${JSON.stringify(ready)}`);
}

export function classifyConnectError(message: string): "auth" | "transport" {
  return message === "unauthorized" ? "auth" : "transport";
}

export function versionProblem(actual: unknown, expected: string | null): string | null {
  if (!expected) return null;
  if (typeof actual !== "string" || actual === "" || actual === "dev") {
    return (
      `api báo version=${String(actual)} — Coolify chưa truyền SOURCE_COMMIT (bật "Include Source Commit in Build", ` +
      "runbook coolify §7) hoặc chạy với SMOKE_EXPECT_VERSION= để bỏ kiểm"
    );
  }
  if (expected.startsWith(actual) || actual.startsWith(expected)) return null;
  return `api đang chạy ${actual}, mong đợi ${expected} — bản deploy chưa lên hoặc container cũ còn chạy`;
}

export function containsText(value: unknown, needle: string): boolean {
  return JSON.stringify(value ?? null).includes(needle);
}

/** Token thô trong link của thư (`/invite/<token>` hoặc `?token=<token>`) — smoke đọc từ outbox console. */
export function tokenFrom(text: string, marker: "/invite/" | "token="): string | null {
  const at = text.indexOf(marker);
  if (at < 0) return null;
  return /^[A-Za-z0-9_-]+/.exec(text.slice(at + marker.length))?.[0] ?? null;
}
