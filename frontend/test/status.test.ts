import { describe, expect, it } from "vitest";

import { checkAll } from "../src/lib/status.ts";

type Reply = { status: number; body: unknown } | "throw";

function fakeFetch(routes: Record<string, Reply>): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input);
    const reply = routes[url];
    if (!reply || reply === "throw") throw new TypeError("network down");
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  }) as typeof fetch;
}

const beats = (ok: boolean) => ({ ok, age_s: ok ? 3 : 120, last: "x" });
const healthy: Record<string, Reply> = {
  "/bizwithagents/api/health/live": { status: 200, body: { data: { version: "abc123" } } },
  "/bizwithagents/api/health/ready": { status: 200, body: { success: true, data: { "postgres.rw": "ok", mongo: "disabled" } } },
  "/bizwithagents/api/health/pipeline": { status: 200, body: { data: { consume: beats(true), work: beats(true), schedule: beats(true) } } },
  "/bizwithagents/ws/health": { status: 200, body: { status: "ok" } },
};

describe("checkAll", () => {
  it("all green when every endpoint is healthy", async () => {
    const r = await checkAll(fakeFetch(healthy));
    expect(r.version).toBe("abc123");
    expect(r.services.map((s) => [s.name, s.light])).toEqual([
      ["api", "up"],
      ["realtime", "up"],
      ["consume", "up"],
      ["work", "up"],
      ["schedule", "up"],
    ]);
  });

  it("api down → red with reason, never throws", async () => {
    const r = await checkAll(fakeFetch({ ...healthy, "/bizwithagents/api/health/ready": "throw", "/bizwithagents/api/health/pipeline": "throw" }));
    const api = r.services.find((s) => s.name === "api")!;
    expect(api.light).toBe("down");
    expect(api.detail).toBe("không phản hồi");
    expect(r.services.find((s) => s.name === "work")!.detail).toBe("chưa có nhịp tim");
  });

  it("503 ready lists failing checks; 503 pipeline still maps per role", async () => {
    const r = await checkAll(
      fakeFetch({
        ...healthy,
        "/bizwithagents/api/health/ready": { status: 503, body: { success: false, data: { "redis.ro": "error: X", "postgres.rw": "ok" } } },
        "/bizwithagents/api/health/pipeline": { status: 503, body: { data: { consume: beats(true), work: beats(false), schedule: beats(true) } } },
      }),
    );
    expect(r.services.find((s) => s.name === "api")!.detail).toBe("lỗi: redis.ro");
    expect(r.services.find((s) => s.name === "work")!.light).toBe("down");
    expect(r.services.find((s) => s.name === "consume")!.light).toBe("up");
  });

  it("realtime degraded → red", async () => {
    const r = await checkAll(fakeFetch({ ...healthy, "/bizwithagents/ws/health": { status: 503, body: { status: "degraded" } } }));
    expect(r.services.find((s) => s.name === "realtime")!.light).toBe("down");
  });

  it("endpoint treo → huỷ sau timeoutMs, đèn đỏ, không treo trang", async () => {
    const ok = fakeFetch(healthy);
    const hanging = ((input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === "/bizwithagents/ws/health"
        ? new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))))
        : ok(input, init)) as typeof fetch;
    const r = await checkAll(hanging, 20);
    const rt = r.services.find((s) => s.name === "realtime")!;
    expect([rt.light, rt.detail]).toEqual(["down", "không phản hồi"]);
    expect(r.services.find((s) => s.name === "api")!.light).toBe("up");
  });
});
