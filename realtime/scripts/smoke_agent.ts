/**
 * Bước smoke agent (profile local — stack thử có LLM giả `fakellm` + agent seed `scripts/seed_agent.py`): chat gọi tool
 * qua socket, tool bị ép "hỏi duyệt" bằng override ở Studio → duyệt → xong, trace có span llm + tool + approval khi Mongo
 * bật. Thứ tự bước ở `AGENT_STEPS`.
 */

import type { Socket } from "socket.io-client";

import { type CallOptions, expect, need, okData, type Reply } from "./smoke_io.ts";
import { sessionFrom, type Session } from "./smoke_lib.ts";

export const AGENT_STEPS = [
  "agent: user1 có trợ lý (agent.list_agents)",
  "agent: chat \"call:notifications_list {}\" → agent:step + agent:end qua socket",
  "agent: override \"hỏi duyệt\" (notifications_mark_all_read) → agent:approval → duyệt → agent:end",
  "agent: trace có span llm + tool + approval (Mongo bật) / enabled=false (Mongo tắt)",
] as const;

type Call = (method: "GET" | "POST", path: string, o?: CallOptions) => Promise<Reply>;
type Ev = { event: string; data: Record<string, unknown> };

export interface AgentDeps {
  step: (name: string, fn: () => Promise<void>) => void;
  call: Call;
  connect: (token: string) => Promise<Socket>;
  ip: (slot: number) => string;
  run: string;
  password: string;
  sockets: Socket[];
  adminToken: () => string;
  mongo: "on" | "off";
}

const EVENTS = ["agent:start", "agent:route", "agent:token", "agent:step", "agent:approval", "agent:approval_decided", "agent:end", "agent:error"];

/** Gom sự kiện `agent:*` theo run (đăng ký trước khi gửi — sự kiện đầu có thể tới trước response). */
export function collector(socket: Socket) {
  const seen: Ev[] = [];
  const waiters: { runId: () => string | undefined; until: string[]; resolve: (e: Ev[]) => void; reject: (err: Error) => void; timer: NodeJS.Timeout }[] = [];
  const check = (): void => {
    for (const w of [...waiters]) {
      const id = w.runId();
      if (!id) continue;
      const mine = seen.filter((e) => e.data.run_id === id);
      const bad = mine.find((e) => e.event === "agent:error");
      if (bad) w.reject(new Error(`agent:error ${JSON.stringify(bad.data).slice(0, 300)}`));
      else if (mine.some((e) => w.until.includes(e.event))) w.resolve(mine);
      else continue;
      clearTimeout(w.timer);
      waiters.splice(waiters.indexOf(w), 1);
    }
  };
  const handlers = EVENTS.map((event) => {
    const h = (data: Record<string, unknown>): void => {
      seen.push({ event, data });
      check();
    };
    socket.on(event, h);
    return [event, h] as const;
  });
  return {
    wait(runId: () => string | undefined, until: string[], ms = 20_000): Promise<Ev[]> {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`không nhận được ${until.join(" / ")} sau ${ms}ms (đã có: ${seen.map((e) => e.event).join(",")})`)), ms);
        waiters.push({ runId, until, resolve, reject, timer });
        check();
      });
    },
    close(): void {
      for (const [event, h] of handlers) socket.off(event, h);
    },
  };
}

export function addAgentSteps(d: AgentDeps): void {
  const s: { u1?: Session; agentId?: string; sessionId?: string; sock?: Socket; runId?: string; col?: ReturnType<typeof collector> } = {};
  const send = async (content: string): Promise<string> => {
    const body = { session_id: s.sessionId ?? null, agent_id: need(s.agentId, "agent"), content, client_msg_id: `smoke-${d.run}-${Math.random().toString(36).slice(2, 10)}` };
    const out = okData(await d.call("POST", "/agent/send", { body, token: need(s.u1, "phiên user1").access }), "agent/send");
    s.sessionId = out.session_id;
    s.runId = out.run_id;
    return out.run_id as string;
  };

  d.step(AGENT_STEPS[0], async () => {
    s.u1 = sessionFrom(okData(await d.call("POST", "/auth/login", { body: { email: "user1@test.local", password: d.password }, ip: d.ip(12) }), "đăng nhập user1"));
    const agents = okData(await d.call("GET", "/agent/list_agents", { token: s.u1.access }), "agent/list_agents") as any[];
    expect(agents.length > 0, "không có agent nào mở cho user1 — chạy scripts/seed_agent.py (make dev-up làm sẵn)");
    s.agentId = agents[0].id;
    s.sock = await d.connect(s.u1.access);
    d.sockets.push(s.sock);
    s.col = collector(s.sock);
  });

  d.step(AGENT_STEPS[1], async () => {
    s.runId = undefined;
    const done = need(s.col, "collector").wait(() => s.runId, ["agent:end"]);
    await send("call:notifications_list {}");
    const events = await done;
    const steps = events.filter((e) => e.event === "agent:step" && e.data.name === "notifications_list");
    expect(steps.some((e) => e.data.status === "done"), `thiếu agent:step notifications_list done: ${JSON.stringify(steps).slice(0, 300)}`);
    const end = events.find((e) => e.event === "agent:end");
    expect(end?.data.status === "done", `agent:end status=${end?.data.status}`);
  });

  d.step(AGENT_STEPS[2], async () => {
    const token = need(s.u1, "phiên user1").access;
    const admin = d.adminToken();
    const agents = okData(await d.call("GET", "/studio/list_agents", { token: admin }), "studio/list_agents") as any[];
    const general = agents.find((a) => a.slug === "general");
    expect(general, "không có chuyên gia general");
    const override = { agent_id: general.id, operation: "notifications.mark_all_read", policy: "confirm" };
    okData(await d.call("POST", "/studio/set_tool_override", { body: override, token: admin }), "studio/set_tool_override");
    try {
      s.runId = undefined;
      const asked = need(s.col, "collector").wait(() => s.runId, ["agent:approval"]);
      await send("call:notifications_mark_all_read {}");
      const approval = (await asked).find((e) => e.event === "agent:approval");
      const runId = need(s.runId, "run");
      const ended = need(s.col, "collector").wait(() => runId, ["agent:end"]);
      okData(await d.call("POST", "/agent/decide_approval", { body: { approval_id: approval?.data.approval_id, approve: true }, token }), "agent/decide_approval");
      const events = await ended;
      const step = events.filter((e) => e.event === "agent:step" && e.data.name === "notifications_mark_all_read").pop();
      expect(step?.data.status === "done", `bước mark_all_read: ${JSON.stringify(step?.data).slice(0, 300)}`);
    } finally {
      await d.call("POST", "/studio/set_tool_override", { body: { ...override, remove: true }, token: admin });
    }
  });

  d.step(AGENT_STEPS[3], async () => {
    const data = okData(await d.call("GET", `/traces/get?run_id=${need(s.runId, "run")}`, { token: d.adminToken() }), "traces/get");
    if (d.mongo === "off") {
      expect(data.enabled === false, `traces/get enabled=${data.enabled}, Mongo tắt`);
      return;
    }
    const kinds = new Set(((data.spans ?? []) as any[]).map((x) => x.kind));
    expect(kinds.has("run") && kinds.has("llm") && kinds.has("tool") && kinds.has("approval"), `span kinds=${[...kinds].join(",")}`);
    s.col?.close();
  });
}
