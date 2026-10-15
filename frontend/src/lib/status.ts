/** Trạng thái các thành phần — gọi health của api / realtime / nhịp tim pipeline; không bao giờ ném lỗi. */

import { apiUrl, wsUrl } from "@/lib/api/url";

export type Light = "up" | "down";

export interface ServiceStatus {
  name: string;
  label: string;
  light: Light;
  detail: string;
}

export interface StatusResult {
  services: ServiceStatus[];
  version: string | null;
}

interface Reply {
  ok: boolean;
  status: number;
  body: unknown;
}

async function getJson(fetchFn: typeof fetch, url: string, timeoutMs: number): Promise<Reply> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetchFn(url, { signal: ctrl.signal, headers: { accept: "application/json" } });
    return { ok: r.ok, status: r.status, body: await r.json().catch(() => null) };
  } catch {
    return { ok: false, status: 0, body: null };
  } finally {
    clearTimeout(timer);
  }
}

function dataOf<T>(reply: Reply): T | undefined {
  return (reply.body as { data?: T } | null)?.data;
}

export async function checkAll(fetchFn: typeof fetch = fetch, timeoutMs = 4000): Promise<StatusResult> {
  const [live, ready, pipeline, ws] = await Promise.all([
    getJson(fetchFn, apiUrl("health/live"), timeoutMs),
    getJson(fetchFn, apiUrl("health/ready"), timeoutMs),
    getJson(fetchFn, apiUrl("health/pipeline"), timeoutMs),
    getJson(fetchFn, wsUrl("health"), timeoutMs),
  ]);
  const failed = Object.entries(dataOf<Record<string, string>>(ready) ?? {})
    .filter(([, v]) => v !== "ok" && v !== "disabled")
    .map(([k]) => k);
  const apiDetail = !ready.status ? "không phản hồi" : failed.length ? `lỗi: ${failed.join(", ")}` : `HTTP ${ready.status}`;
  const beats = dataOf<Record<string, { ok: boolean; age_s: number | null }>>(pipeline) ?? {};
  const role = (name: string, label: string): ServiceStatus => {
    const b = beats[name];
    return {
      name,
      label,
      light: b?.ok ? "up" : "down",
      detail: b?.age_s == null ? "chưa có nhịp tim" : `nhịp tim ${b.age_s}s trước`,
    };
  };
  return {
    version: dataOf<{ version?: string }>(live)?.version ?? null,
    services: [
      { name: "api", label: "API", light: ready.ok ? "up" : "down", detail: apiDetail },
      { name: "realtime", label: "Realtime", light: ws.ok ? "up" : "down", detail: ws.status ? `HTTP ${ws.status}` : "không phản hồi" },
      role("consume", "Consumer"),
      role("work", "Worker"),
      role("schedule", "Scheduler"),
    ],
  };
}
