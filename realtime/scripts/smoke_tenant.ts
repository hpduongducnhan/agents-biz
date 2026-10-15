/**
 * Bước smoke tenant + mail (profile local / docker — có ghi dữ liệu, cần transport thư `console`): superadmin tạo tổ chức
 * mới + mời admin qua email → thư ở outbox → đăng ký bằng link mời → admin tổ chức mới chỉ thấy user của mình (REST) và
 * socket tổ chức khác không nhận `data:changed` của tổ chức mới (D11, D13) → quên mật khẩu → thư → đặt lại → đăng nhập.
 */

import type { Socket } from "socket.io-client";

import { type CallOptions, expect, need, okData, poll, type Reply, waitEvent } from "./smoke_io.ts";
import { sessionFrom, tokenFrom, type Session } from "./smoke_lib.ts";

export const TENANT_STEPS = [
  "tenant: superadmin tạo tổ chức + mời admin → thư mời ở outbox console",
  "tenant: đăng ký bằng link mời → vào đúng tổ chức, role admin",
  "tenant: admin tổ chức mới chỉ thấy user của mình; socket tổ chức khác không nhận data:changed",
  "mail: quên mật khẩu → thư ở outbox → đặt lại → đăng nhập bằng mật khẩu mới",
  "agent theo tenant: tổ chức khác không đọc được phiên chat (404); tắt trợ lý cho tổ chức → 6023, danh sách agent rỗng",
  "tasks: tạo việc ở tổ chức mới → data:changed tới tổ chức đó, tổ chức khác không thấy (404) và không nhận realtime",
] as const;

type Call = (method: "GET" | "POST", path: string, o?: CallOptions) => Promise<Reply>;

export interface TenantDeps {
  step: (name: string, fn: () => Promise<void>) => void;
  call: Call;
  connect: (token: string) => Promise<Socket>;
  ip: (slot: number) => string;
  run: string;
  adminToken: () => string;
  /** Socket của một user tổ chức khác (tenant `default`) — không được nhận sự kiện của tổ chức mới. */
  otherSocket: () => Socket;
  /** Mật khẩu tài khoản seed (`user1@test.local` — tenant `default`, member). */
  password: string;
  sockets: Socket[];
}

type Mail = { to: string; subject: string; text: string };

async function mailTo(d: TenantDeps, email: string, marker: "/invite/" | "token="): Promise<string> {
  let token = "";
  await poll(`outbox chưa có thư tới ${email} (task mail.send?)`, 15_000, async () => {
    const data = okData(await d.call("GET", "/mail/outbox?limit=50", { token: d.adminToken() }), "mail/outbox");
    expect(data?.enabled === true, "mail/outbox enabled=false — smoke cần MAIL_TRANSPORT=console");
    const mail = ((data.items ?? []) as Mail[]).find((m) => m.to === email && tokenFrom(m.text, marker));
    token = (mail && tokenFrom(mail.text, marker)) || "";
    return token !== "";
  });
  return token;
}

export function addTenantSteps(d: TenantDeps): void {
  const email = `owner-${d.run}@smoke.test`;
  const password = "smoke-owner-1";
  const state: { tenantId?: string; inviteToken?: string; owner?: Session; socket?: Socket } = {};

  d.step(TENANT_STEPS[0], async () => {
    const body = { name: `Smoke ${d.run}`, admin_email: email };
    const out = okData(await d.call("POST", "/tenants/create", { body, token: d.adminToken() }), "tenants/create");
    expect(out?.tenant?.id && out?.invite?.email === email, `tenants/create không trả tenant + lời mời: ${JSON.stringify(out)}`);
    state.tenantId = out.tenant.id;
    state.inviteToken = await mailTo(d, email, "/invite/");
  });

  d.step(TENANT_STEPS[1], async () => {
    const token = need(state.inviteToken, "token mời");
    const preview = okData(await d.call("GET", `/invites/preview?token=${encodeURIComponent(token)}`), "invites/preview");
    expect(preview?.role_name === "admin", `invites/preview role=${preview?.role_name}, mong đợi admin`);
    const body = { email, password, name: "Smoke Owner", invite_token: token };
    const s = sessionFrom(okData(await d.call("POST", "/auth/register", { body, ip: d.ip(4) }), "auth/register (lời mời)"));
    const me = okData(await d.call("GET", "/auth/me", { token: s.access }), "auth/me");
    expect(me?.tenant?.id === state.tenantId, `user mới ở tenant ${me?.tenant?.id}, mong đợi ${state.tenantId}`);
    expect(s.perms.includes("tenant.invite") && s.perms.includes("user.view"), `admin tổ chức thiếu quyền: [${s.perms.join(", ")}]`);
    state.owner = s;
  });

  d.step(TENANT_STEPS[2], async () => {
    const owner = need(state.owner, "phiên admin tổ chức mới");
    const users = okData(await d.call("GET", "/admin/list_users?limit=100", { token: owner.access }), "admin/list_users");
    const emails = ((users?.items ?? []) as { email: string }[]).map((u) => u.email);
    expect(emails.length === 1 && emails[0] === email, `admin tổ chức mới thấy user ngoài tổ chức: ${emails.join(", ")}`);
    state.socket = await d.connect(owner.access);
    d.sockets.push(state.socket);
    const leaked: unknown[] = [];
    const spy = (data: { keys?: string[] }): void => void (data?.keys?.includes("tenant.current") && leaked.push(data));
    const other = d.otherSocket();
    other.on("data:changed", spy);
    try {
      const mine = waitEvent(state.socket, ["data:changed"]);
      okData(await d.call("POST", "/tenant/update", { body: { name: `Smoke ${d.run} đổi tên` }, token: owner.access }), "tenant/update");
      const { data } = await mine;
      expect((data as { keys?: string[] })?.keys?.includes("tenant.current"), `data:changed thiếu tenant.current: ${JSON.stringify(data)}`);
      await new Promise((r) => setTimeout(r, 500));
      expect(leaked.length === 0, `socket tổ chức khác nhận data:changed của tổ chức mới: ${JSON.stringify(leaked)}`);
    } finally {
      other.off("data:changed", spy);
    }
  });

  d.step(TENANT_STEPS[3], async () => {
    okData(await d.call("POST", "/auth/forgot_password", { body: { email }, ip: d.ip(5) }), "auth/forgot_password");
    const token = await mailTo(d, email, "token=");
    const fresh = "smoke-owner-2";
    okData(await d.call("POST", "/auth/reset_password", { body: { token, new_password: fresh } }), "auth/reset_password");
    const old = await d.call("POST", "/auth/login", { body: { email, password }, ip: d.ip(5) });
    expect(old.body?.code === 2102, `mật khẩu cũ vẫn đăng nhập được: ${old.status}/${old.body?.code}`);
    const relogin = await d.call("POST", "/auth/login", { body: { email, password: fresh }, ip: d.ip(5) });
    state.owner = sessionFrom(okData(relogin, "auth/login (mật khẩu mới)"));
    const again = await d.call("POST", "/auth/reset_password", { body: { token, new_password: "smoke-owner-3" } });
    expect(again.body?.code === 2114, `token đặt lại dùng lần hai → ${again.status}/${again.body?.code}, mong đợi 2114`);
  });

  d.step(TENANT_STEPS[4], async () => {
    const owner = need(state.owner, "phiên admin tổ chức mới");
    const body = { content: "smoke tenant", client_msg_id: `smoke-${d.run}`, auto: true };
    const sent = okData(await d.call("POST", "/agent/send", { body, token: owner.access }), "agent/send (tổ chức mới)");
    const login = await d.call("POST", "/auth/login", { body: { email: "user1@test.local", password: d.password }, ip: d.ip(6) });
    const other = sessionFrom(okData(login, "auth/login user1 (tenant default)"));
    const peek = await d.call("GET", `/agent/get_session?session_id=${sent.session_id}`, { token: other.access });
    expect(peek.status === 404 && peek.body?.code === 6004, `user tổ chức khác đọc phiên chat → ${peek.status}/${peek.body?.code}`);
    const policies = { tenant_id: need(state.tenantId, "tenant"), policies: { agent_enabled: false } };
    okData(await d.call("POST", "/tenants/update", { body: policies, token: d.adminToken() }), "tenants/update (tắt trợ lý)");
    const off = await d.call("POST", "/agent/send", { body: { ...body, client_msg_id: `smoke-off-${d.run}` }, token: owner.access });
    expect(off.status === 403 && off.body?.code === 6023, `tổ chức tắt trợ lý vẫn gửi được: ${off.status}/${off.body?.code}`);
    const agents = okData(await d.call("GET", "/agent/list_agents", { token: owner.access }), "agent/list_agents");
    expect(Array.isArray(agents) && agents.length === 0, `tổ chức tắt trợ lý vẫn thấy agent: ${JSON.stringify(agents)}`);
    const me = okData(await d.call("GET", "/auth/me", { token: owner.access }), "auth/me");
    expect(me?.tenant?.agent_enabled === false, `auth/me tenant.agent_enabled=${me?.tenant?.agent_enabled}`);
  });

  d.step(TENANT_STEPS[5], async () => {
    const owner = need(state.owner, "phiên admin tổ chức mới");
    const socket = need(state.socket, "socket admin tổ chức mới");
    const other = d.otherSocket();
    const leaked: unknown[] = [];
    const spy = (data: { keys?: string[] }): void => void (data?.keys?.includes("tasks.list") && leaked.push(data));
    other.on("data:changed", spy);
    try {
      const mine = waitEvent(socket, ["data:changed"]);
      const body = { title: `Smoke task ${d.run}`, priority: "high" };
      const task = okData(await d.call("POST", "/tasks/create", { body, token: owner.access }), "tasks/create");
      const { data } = await mine;
      expect((data as { keys?: string[] })?.keys?.includes("tasks.list"), `data:changed thiếu tasks.list: ${JSON.stringify(data)}`);
      const login = await d.call("POST", "/auth/login", { body: { email: "user1@test.local", password: d.password }, ip: d.ip(7) });
      const user1 = sessionFrom(okData(login, "auth/login user1 (tenant default)"));
      const peek = await d.call("GET", `/tasks/get?task_id=${task.id}`, { token: user1.access });
      expect(peek.status === 404 && peek.body?.code === 10001, `tổ chức khác đọc được việc: ${peek.status}/${peek.body?.code}`);
      const list = okData(await d.call("GET", `/tasks/list?q=${encodeURIComponent(body.title)}`, { token: user1.access }), "tasks/list");
      expect(list?.total === 0, `tổ chức khác thấy việc trong danh sách: ${JSON.stringify(list).slice(0, 200)}`);
      await new Promise((r) => setTimeout(r, 500));
      expect(leaked.length === 0, `socket tổ chức khác nhận data:changed của Tasks: ${JSON.stringify(leaked)}`);
    } finally {
      other.off("data:changed", spy);
    }
  });
}
