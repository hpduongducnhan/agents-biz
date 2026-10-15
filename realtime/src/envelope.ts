/** Envelope v1 + tên exchange — phải khớp backend (`backend/app/core/messaging/names.py`, realtime.md §2). */

import type { Claims } from "./auth.ts";

export const RT_OUT = "bw.rt.out";
export const RT_IN = "bw.rt.in";
export const RT_UNROUTED = "bw.rt.in.unrouted";
export const ENVELOPE_VERSION = 1;

const CLIENT_EVENT = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/;
const OUT_EVENT = /^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$/; // như backend — không bao giờ trùng tên dành riêng của Socket.IO
export const CONTROL_PREFIX = "rt:"; // lệnh cho chính service realtime, không chuyển tới client

export interface OutEnvelope {
  v: number;
  event: string;
  data: unknown;
  cid: string | null;
  ts: string;
}

export function isClientEvent(name: unknown): name is string {
  return typeof name === "string" && CLIENT_EVENT.test(name);
}

export function isOutEvent(name: string): boolean {
  return OUT_EVENT.test(name);
}

export function roomFor(routingKey: string): { room: string } | { all: true } | null {
  if (routingKey === "all") return { all: true };
  if (routingKey === "sup") return { room: "sup" };
  const m = /^(user|tenant)\.(.+)$/.exec(routingKey);
  return m ? { room: `${m[1]}:${m[2]}` } : null;
}

export function keysFor(c: Pick<Claims, "sub" | "sup" | "tid">): string[] {
  return [`user.${c.sub}`, ...(c.tid ? [`tenant.${c.tid}`] : []), ...(c.sup ? ["sup"] : [])];
}

export function inboundEnvelope(event: string, data: unknown, claims: Claims, sid: string, cid: string) {
  const { sub, tid, perms, sup } = claims;
  return { v: ENVELOPE_VERSION, event, data, claims: { sub, tid: tid ?? null, perms, sup }, sid, cid, ts: new Date().toISOString() };
}
