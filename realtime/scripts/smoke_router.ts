/**
 * Bước smoke router (profile local — LLM giả + "Assistant" là orchestrator): dựng chuyên gia phụ `smoke_helper` qua
 * Studio (lần đầu), router chọn 2 bước, hỏi lại khi mơ hồ, `handoff` chuyển chuyên gia. Kiểm `agent:route` + trường `by`
 * của từng khối. Thứ tự bước ở `ROUTER_STEPS`.
 */

import type { Socket } from "socket.io-client";

import { collector } from "./smoke_agent.ts";
import { type CallOptions, expect, need, okData, type Reply } from "./smoke_io.ts";
import { sessionFrom, type Session } from "./smoke_lib.ts";

export const ROUTER_STEPS = [
  "router: có chuyên gia phụ smoke_helper (tạo qua Studio nếu thiếu) + route từ Assistant",
  "router: 2 bước (general → smoke_helper) — agent:route + khối by đúng thứ tự",
  "router: mơ hồ → clarify (không gọi chuyên gia)",
  "router: handoff general → smoke_helper trong một lượt",
] as const;

const HELPER = "smoke_helper";

type Call = (method: "GET" | "POST", path: string, o?: CallOptions) => Promise<Reply>;
type Ev = { event: string; data: Record<string, any> };

export interface RouterDeps {
  step: (name: string, fn: () => Promise<void>) => void;
  call: Call;
  connect: (token: string) => Promise<Socket>;
  ip: (slot: number) => string;
  run: string;
  password: string;
  sockets: Socket[];
  adminToken: () => string;
}

const slugs = (events: Ev[], name: string) => [...new Set(events.filter((e) => e.event === name && e.data.by).map((e) => e.data.by.slug))];

/** Chuyên gia phụ chép model + pool key của Assistant, toolset `lookup`, route ở cuối bảng. Chạy lại không tạo trùng. */
async function ensureHelper(d: RouterDeps): Promise<void> {
  const token = d.adminToken();
  const agents = okData(await d.call("GET", "/studio/list_agents", { token }), "studio/list_agents") as any[];
  const assistant = agents.find((a) => a.slug === "assistant");
  expect(assistant?.model_id, "Assistant chưa có model — chạy scripts/seed_agent.py (make dev-up làm sẵn)");
  let helper = agents.find((a) => a.slug === HELPER);
  if (!helper) {
    const body = { slug: HELPER, name: "Smoke helper", description: "Chuyên gia phụ cho smoke router", instructions: "Trả lời ngắn.", visible_to: "roles", model_id: assistant.model_id };
    helper = okData(await d.call("POST", "/studio/save_agent", { body, token }), "studio/save_agent");
    okData(await d.call("POST", "/studio/set_toolsets", { body: { agent_id: helper.id, toolsets: ["lookup"] }, token }), "studio/set_toolsets");
    const keys = (assistant.keys ?? []).map((k: any) => ({ credential_id: k.credential_id, enabled: true }));
    okData(await d.call("POST", "/studio/set_agent_keys", { body: { agent_id: helper.id, keys }, token }), "studio/set_agent_keys");
  }
  const routes = okData(await d.call("GET", `/studio/list_routes?orchestrator_id=${assistant.id}`, { token }), "studio/list_routes") as any[];
  if (!routes.some((r) => r.slug === HELPER)) {
    const body = { orchestrator_id: assistant.id, agent_id: helper.id, intent: "Smoke helper — chỉ dùng cho smoke", examples: ["smoke helper"], position: 900 };
    okData(await d.call("POST", "/studio/save_route", { body, token }), "studio/save_route");
  }
}

export function addRouterSteps(d: RouterDeps): void {
  const s: { u?: Session; agentId?: string; runId?: string; col?: ReturnType<typeof collector> } = {};
  const send = async (content: string): Promise<void> => {
    const body = { session_id: null, agent_id: need(s.agentId, "agent"), content, client_msg_id: `smoke-${d.run}-${Math.random().toString(36).slice(2, 10)}` };
    s.runId = undefined;
    const out = okData(await d.call("POST", "/agent/send", { body, token: need(s.u, "phiên user1").access }), "agent/send");
    s.runId = out.run_id;
  };
  const turn = async (content: string): Promise<Ev[]> => {
    s.runId = undefined;
    if (!s.col) {
      s.u = sessionFrom(okData(await d.call("POST", "/auth/login", { body: { email: "user1@test.local", password: d.password }, ip: d.ip(13) }), "đăng nhập user1"));
      const agents = okData(await d.call("GET", "/agent/list_agents", { token: s.u.access }), "agent/list_agents") as any[];
      s.agentId = agents.find((a) => a.slug === "assistant")?.id;
      expect(s.agentId, "không có agent assistant");
      const sock = await d.connect(s.u.access);
      d.sockets.push(sock);
      s.col = collector(sock);
    }
    const done = need(s.col, "collector").wait(() => s.runId, ["agent:end"]);
    await send(content);
    return (await done) as Ev[];
  };

  d.step(ROUTER_STEPS[0], () => ensureHelper(d));

  d.step(ROUTER_STEPS[1], async () => {
    const events = await turn(`route:general,${HELPER} call:notifications_list {} | nói xin chào`);
    const route = events.find((e) => e.event === "agent:route");
    expect(route?.data.steps?.map((x: any) => x.slug).join(",") === `general,${HELPER}`, `agent:route ${String(JSON.stringify(route?.data)).slice(0, 300)}`);
    const stepBy = events.find((e) => e.event === "agent:step" && e.data.name === "notifications_list")?.data.by?.slug;
    expect(stepBy === "general", `bước notifications_list by=${stepBy}`);
    const order = slugs(events, "agent:token");
    expect(order.join(",") === `general,${HELPER}`, `thứ tự khối chữ theo by: ${order.join(",")}`);
  });

  d.step(ROUTER_STEPS[2], async () => {
    const events = await turn("clarify:Bạn muốn làm việc gì?");
    const route = events.find((e) => e.event === "agent:route");
    expect(route?.data.clarify === "Bạn muốn làm việc gì?" && (route?.data.steps ?? []).length === 0, `agent:route ${JSON.stringify(route?.data)}`);
    expect(!events.some((e) => e.event === "agent:step"), "clarify không được gọi tool");
  });

  d.step(ROUTER_STEPS[3], async () => {
    const events = await turn(`route:general call:handoff {"to": "${HELPER}", "reason": "việc của chuyên gia phụ"}`);
    const handoff = events.find((e) => e.event === "agent:step" && e.data.name === "handoff" && e.data.status === "done");
    expect(handoff?.data.by?.slug === "general", `bước handoff ${JSON.stringify(handoff?.data).slice(0, 200)}`);
    expect(slugs(events, "agent:token").includes(HELPER), `không có khối chữ của ${HELPER}: ${slugs(events, "agent:token").join(",")}`);
    s.col?.close();
  });
}
