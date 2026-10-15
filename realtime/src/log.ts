/** Log cùng định dạng backend (logger `bw`, trường cố định, JSON / text theo LOG_JSON) — grep chung được. */

import type { Writable } from "node:stream";

const LEVELS = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 } as const;
type Level = keyof typeof LEVELS;
const SENSITIVE = /^(token|authorization|password|secret|refresh_token|access_token)$/i;

export type Fields = Record<string, unknown> & { loc?: string; cid?: string | null };

export interface Logger {
  debug(msg: string, fields?: Fields): void;
  info(msg: string, fields?: Fields): void;
  warn(msg: string, fields?: Fields): void;
  error(msg: string, fields?: Fields): void;
}

function pad(n: number, width = 2): string {
  return String(n).padStart(width, "0");
}

function redact(fields: Fields): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fields)) {
    if (k === "loc" || k === "cid") continue;
    out[k] = SENSITIVE.test(k) ? "[REDACTED]" : v;
  }
  return out;
}

function short(v: unknown): string {
  return typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
}

export function createLogger(opts: { json: boolean; level: string; stream?: Writable }): Logger {
  const min = LEVELS[(opts.level.toUpperCase() === "WARN" ? "WARNING" : opts.level.toUpperCase()) as Level] ?? 20;
  const out = opts.stream ?? process.stdout;

  function write(level: Level, msg: string, fields: Fields = {}): void {
    if (LEVELS[level] < min) return;
    const now = new Date();
    const loc = fields.loc || "-";
    const cid = fields.cid || "-";
    const extra = redact(fields);
    let line: string;
    if (opts.json) {
      line = JSON.stringify({
        ts: now.toISOString(),
        level,
        logger: "bw",
        proc: "realtime",
        module: "core",
        loc,
        cid,
        msg,
        ...extra,
      });
    } else {
      const ts = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.${pad(now.getMilliseconds(), 3)}`;
      const parts = [ts, level.padEnd(7), "realtime", `cid=${cid}`];
      if (fields.loc) parts.push(`[${fields.loc}]`);
      parts.push(msg);
      const kv = Object.entries(extra).map(([k, v]) => `${k}=${short(v)}`);
      if (kv.length) parts.push(kv.join(" "));
      line = parts.join(" ");
    }
    out.write(`${line}\n`);
  }

  return {
    debug: (m, f) => write("DEBUG", m, f),
    info: (m, f) => write("INFO", m, f),
    warn: (m, f) => write("WARNING", m, f),
    error: (m, f) => write("ERROR", m, f),
  };
}
