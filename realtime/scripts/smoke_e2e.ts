/**
 * Smoke đầu-cuối BizWithAgents — đi qua cửa web như trình duyệt: bundle + SPA fallback (+ cache), API qua proxy, chế độ Mongo,
 * IP thật cho rate limit đăng nhập, websocket + sự kiện realtime, tách tenant + thư (outbox console), khoá tài khoản,
 * event log / issues.
 *   node scripts/smoke_e2e.ts <url gốc> --profile local|docker|prod
 * local / docker có ghi dữ liệu (đăng ký, role, khoá user) — chỉ chạy với máy local. prod không ghi dữ liệu.
 */

import type { Socket } from "socket.io-client";

import { door, dump, expect, need, okData, poll, waitEvent } from "./smoke_io.ts";
import { addAgentSteps } from "./smoke_agent.ts";
import { addPwaSteps } from "./smoke_pwa.ts";
import { addRouterSteps } from "./smoke_router.ts";
import { addTenantSteps } from "./smoke_tenant.ts";
import {
  assetPaths,
  cacheProblems,
  containsText,
  fakeIp,
  isDevServer,
  mongoMode,
  parseOptions,
  rateLimitEnabled,
  sessionFrom,
  versionProblem,
  type AssetCheck,
  type Options,
  type Session,
} from "./smoke_lib.ts";

function options(): Options {
  try {
    return parseOptions(process.argv.slice(2), process.env);
  } catch (err) {
    console.log(`✗ ${(err as Error).message}`);
    process.exit(2);
  }
}

const opts = options();
const servicePath = process.env.SERVICE_PATH ?? "bizwithagents";
const { wsBase, call, connect, expectRefused, bindingCount } = door(opts.base, servicePath);
const run = opts.runId;
const ip = (slot: number): string => fakeIp(run, slot);
const targetEmail = `smoke-${run}@smoke.test`;
const roleName = `smoke-${run}`;
const noteTitle = `Smoke ${run}`;
const PASSWORD = "smoke-password-1";
console.log(
  `smoke: profile=${opts.profile} base=${opts.base} mongo=${opts.expectMongo} admin=${opts.admin?.email ?? "-"} ` +
    `login=${opts.prodLogin?.email ?? "-"} version=${opts.expectVersion ?? "-"} run=${run}`,
);

interface Step {
  name: string;
  fn?: () => Promise<void>;
  skip?: string;
}

const plan: Step[] = [];
const step = (name: string, fn: () => Promise<void>): void => void plan.push({ name, fn });
const skip = (name: string, why: string): void => void plan.push({ name, skip: why });
const ctx: { signupOpen?: boolean; admin?: Session; target?: Session; socket?: Socket } = {};

// ── Mọi profile: cửa web, phiên bản, health, realtime, thông tin công khai ──

step(opts.profile === "local" ? "web: bundle + SPA fallback" : "web: bundle + SPA fallback + cache", async () => {
  const index = await fetch(`${opts.base}/`);
  const html = await index.text();
  expect(index.status === 200 && html.includes('id="root"'), `GET / → HTTP ${index.status}`);
  const deep = await fetch(`${opts.base}/admin/users`);
  expect(deep.status === 200 && (await deep.text()).includes('id="root"'), `SPA fallback hỏng: GET /admin/users → HTTP ${deep.status}`);
  if (isDevServer(html)) {
    expect(opts.profile === "local", "cửa web đang là Vite dev server — chỉ chấp nhận ở profile local");
    const entry = await fetch(`${opts.base}/src/main.tsx`);
    expect(entry.status === 200, `GET /src/main.tsx → HTTP ${entry.status}`);
    return;
  }
  const assets: AssetCheck[] = [];
  for (const path of assetPaths(html)) {
    const a = await fetch(`${opts.base}${path}`);
    await a.arrayBuffer();
    assets.push({ path, status: a.status, cacheControl: a.headers.get("cache-control") });
  }
  if (opts.profile === "local") {
    expect(assets.length > 0 && assets.every((a) => a.status === 200), `asset của bundle lỗi: ${JSON.stringify(assets)}`);
    return;
  }
  const problems = cacheProblems(
    { cacheControl: index.headers.get("cache-control"), cfCacheStatus: index.headers.get("cf-cache-status") },
    assets,
  );
  expect(problems.length === 0, problems.join("; "));
});

const expectedVersion = opts.expectVersion;
if (expectedVersion) {
  step("phiên bản api = commit vừa deploy", async () => {
    const live = okData(await call("GET", "/health/live"), "health/live");
    const problem = versionProblem(live?.version, expectedVersion);
    expect(problem === null, problem ?? "");
  });
} else {
  skip("phiên bản api = commit vừa deploy", "không đặt SMOKE_EXPECT_VERSION");
}

step(`api ready + Mongo ${opts.expectMongo}`, async () => {
  const r = await call("GET", "/health/ready");
  expect(r.status === 200, `health/ready → ${dump(r)}`);
  const mode = mongoMode((r.body?.data ?? {}) as Record<string, unknown>);
  expect(mode === opts.expectMongo, `stack đang chạy Mongo ${mode}, mong đợi ${opts.expectMongo} (SMOKE_EXPECT_MONGO)`);
});

step("pipeline: nhịp tim consume / work / schedule", async () => {
  await poll("health/pipeline chưa xanh", 90_000, async () => (await call("GET", "/health/pipeline")).status === 200);
});

step("realtime health", async () => {
  const r = await fetch(`${wsBase}/health`);
  const body = (await r.json().catch(() => null)) as { status?: string } | null;
  expect(r.status === 200 && body?.status === "ok", `${wsBase}/health → HTTP ${r.status} ${JSON.stringify(body)}`);
});

step("system.public_info (công khai)", async () => {
  const info = okData(await call("GET", "/system/public_info"), "system/public_info");
  expect(typeof info?.signup_open === "boolean", `public_info thiếu signup_open: ${JSON.stringify(info)}`);
  ctx.signupOpen = info.signup_open as boolean;
});

step("websocket qua proxy: token sai bị server từ chối (không phải lỗi transport)", async () => {
  await expectRefused("not-a-jwt");
});

if (opts.profile === "prod") {
  // ── prod: không ghi dữ liệu ──

  step("prod không có công cụ dev (/devtools/* → 404)", async () => {
    const r = await call("POST", "/devtools/raise_error", { body: {} });
    expect(r.status === 404, `POST /devtools/raise_error → ${dump(r)} — mong đợi 404 (ENV của Coolify phải là prod)`);
  });

  addPwaSteps({ step, call, base: opts.base });

  step("agent: route trợ lý / Studio / trace có thật (chưa đăng nhập → 401) + /assistant là trang SPA", async () => {
    for (const path of ["/agent/list_agents", "/studio/list_agents", "/studio/list_routes?orchestrator_id=00000000-0000-0000-0000-000000000000", "/traces/list"]) {
      const r = await call("GET", path);
      expect(r.status === 401 && r.body?.code === 1004, `GET ${path} → ${dump(r)} — mong đợi 401 / 1004 (route chưa deploy?)`);
    }
    const page = await fetch(`${opts.base}/assistant`);
    expect(page.status === 200 && (page.headers.get("content-type") ?? "").includes("text/html"), `/assistant → ${page.status}`);
  });

  const login = opts.prodLogin;
  const loginStep = "prod: đăng nhập tài khoản smoke → me → socket → (superadmin) log + status → đăng xuất";
  if (login) {
    step(loginStep, async () => {
      const s = sessionFrom(okData(await call("POST", "/auth/login", { body: login }), "auth/login"));
      try {
        okData(await call("GET", "/auth/me", { token: s.access }), "auth/me");
        (await connect(s.access)).close();
        if (s.sup) {
          for (const path of ["/observability/list_events?limit=1", "/observability/list_issues?limit=1"]) {
            const data = okData(await call("GET", path, { token: s.access }), path);
            expect(data?.enabled === (opts.expectMongo === "on"), `${path} enabled=${data?.enabled}, mong đợi Mongo ${opts.expectMongo}`);
          }
          okData(await call("GET", "/system/status", { token: s.access }), "system/status");
        }
      } finally {
        await call("POST", "/auth/logout", { body: { refresh_token: s.refresh } });
      }
    });
  } else {
    skip(loginStep, "chưa có SMOKE_EMAIL / SMOKE_PASSWORD trong .secrets/smoke.env");
  }

  const rlStep = "prod: rate limit đăng nhập (SMOKE_RATE_LIMIT=1)";
  if (rateLimitEnabled(opts)) {
    step(rlStep, async () => {
      const probe = { email: `ratelimit-${run}@smoke.test`, password: "sai-mat-khau-1" };
      const statuses: number[] = [];
      for (let i = 0; i < 6; i++) statuses.push((await call("POST", "/auth/login", { body: probe, ip: ip(2) })).status);
      expect(statuses[5] === 429, `6 lần sai → ${statuses.join(",")} — lần 6 phải 429 (Cloudflare ghi đè IP giả nên vẫn bị đếm)`);
    });
  } else {
    skip(rlStep, "SMOKE_RATE_LIMIT khác 1");
  }
} else {
  // ── local / docker: có ghi dữ liệu ──
  const admin = opts.admin;
  if (admin === null) throw new Error("profile ghi dữ liệu cần tài khoản superadmin");

  step(
    opts.profile === "docker"
      ? "superadmin: đăng ký email trong SUPERADMIN_EMAILS — JWT có sup"
      : "superadmin: đăng nhập tài khoản seed — JWT có sup",
    async () => {
      let r = await call("POST", opts.profile === "docker" ? "/auth/register" : "/auth/login", { body: admin, ip: ip(0) });
      if (opts.profile === "docker" && r.body?.code === 2101) r = await call("POST", "/auth/login", { body: admin, ip: ip(0) });
      const s = sessionFrom(okData(r, `phiên ${admin.email}`));
      expect(s.sup, `${admin.email} không có sup — email phải nằm trong SUPERADMIN_EMAILS (local: .env; docker: deploy/smoke*.env)`);
      ctx.admin = s;
    },
  );

  step("đăng ký user mới — JWT không có sup", async () => {
    expect(ctx.signupOpen, "signup_open=false — bật đăng ký ở /sa/settings (hoặc dùng DB mới) rồi chạy lại");
    const body = { email: targetEmail, password: PASSWORD };
    ctx.target = sessionFrom(okData(await call("POST", "/auth/register", { body, ip: ip(1) }), `đăng ký ${targetEmail}`));
    expect(!ctx.target.sup, "user mới không được có sup");
  });

  step("rate limit đăng nhập theo IP + email; IP thật qua proxy; superadmin không bị khoá nhầm", async () => {
    const probe = { email: `ratelimit-${run}@smoke.test`, password: "sai-mat-khau-1" };
    const codes: string[] = [];
    for (let i = 0; i < 6; i++) {
      const r = await call("POST", "/auth/login", { body: probe, ip: ip(2) });
      codes.push(`${r.status}/${r.body?.code}`);
    }
    expect(
      codes.slice(0, 5).every((c) => c.endsWith("/2102")) && codes[5]?.startsWith("429"),
      `IP ${ip(2)}: ${codes.join(", ")} — mong đợi 5 lần 2102 rồi 429`,
    );
    const other = await call("POST", "/auth/login", { body: probe, ip: ip(3) });
    expect(other.body?.code === 2102, `IP khác vẫn bị chặn (${dump(other)}) — proxy chưa chuyển IP thật (CF-Connecting-IP / X-Forwarded-For)`);
    const again = await call("POST", "/auth/login", { body: admin, ip: ip(2) });
    expect(again.status === 200, `superadmin đăng nhập từ IP vừa bị chặn → ${dump(again)} — khoá phải theo IP + email`);
  });

  step("realtime: user bắt tay socket bằng token thật (đã bind user.<id>)", async () => {
    const before = await bindingCount();
    ctx.socket = await connect(need(ctx.target, "phiên user").access);
    await poll("realtime chưa bind user.<id> lên RabbitMQ", 5_000, async () => (await bindingCount()) > before);
  });

  step("RBAC: tạo role + gán → core:rbac_updated; refresh có user.view", async () => {
    const token = need(ctx.admin, "phiên superadmin").access;
    const target = need(ctx.target, "phiên user");
    const role = okData(
      await call("POST", "/rbac/create_role", { body: { name: roleName, description: "smoke", permissions: ["user.view"] }, token }),
      "rbac/create_role",
    );
    expect(role?.id !== undefined && role?.id !== null, `rbac/create_role không trả id: ${JSON.stringify(role)}`);
    const got = waitEvent(need(ctx.socket, "socket"), ["core:rbac_updated"]);
    okData(await call("POST", "/admin/update_user", { body: { user_id: target.sub, role_ids: [role.id] }, token }), "admin/update_user (gán role)");
    await got;
    const fresh = sessionFrom(okData(await call("POST", "/auth/refresh", { body: { refresh_token: target.refresh } }), "auth/refresh"));
    expect(fresh.perms.includes("user.view"), `token mới chưa có user.view: [${fresh.perms.join(", ")}]`);
    ctx.target = fresh;
  });

  step("thông báo: core:notification tới đúng user (notifications.send_test)", async () => {
    const got = waitEvent(need(ctx.socket, "socket"), ["core:notification"]);
    const token = need(ctx.admin, "phiên superadmin").access;
    okData(await call("POST", "/notifications/send_test", { body: { email: targetEmail, title: noteTitle }, token }), "notifications/send_test");
    const { data } = await got;
    expect(containsText(data, noteTitle), `core:notification không mang tiêu đề "${noteTitle}": ${JSON.stringify(data)}`);
  });

  step("lỗi có chủ đích → 500 + mã tra cứu", async () => {
    const token = need(ctx.admin, "phiên superadmin").access;
    const r = await call("POST", "/devtools/raise_error", { body: { note: run }, token });
    expect(r.status === 500 && r.body?.code === 1000 && Boolean(r.body?.correlation_id), `devtools/raise_error → ${dump(r)}`);
  });

  step(`event log + issues khi Mongo ${opts.expectMongo}`, async () => {
    const token = need(ctx.admin, "phiên superadmin").access;
    const events = "/observability/list_events?limit=100";
    const issues = "/observability/list_issues?limit=100";
    if (opts.expectMongo === "off") {
      for (const path of [events, issues]) {
        const data = okData(await call("GET", path, { token }), path);
        expect(
          data?.enabled === false && Array.isArray(data?.items) && data.items.length === 0,
          `${path} khi tắt Mongo phải {enabled:false, items:[]}: ${JSON.stringify(data).slice(0, 300)}`,
        );
      }
      return;
    }
    const sub = need(ctx.target, "phiên user").sub;
    await poll("event log chưa có rbac.create_role + admin.update_user của lượt này", 20_000, async () => {
      const data = okData(await call("GET", events, { token }), events);
      expect(data?.enabled === true, `list_events enabled=${data?.enabled}`);
      const items = (data.items ?? []) as { operation?: string }[];
      const created = items.some((i) => i.operation === "rbac.create_role" && containsText(i, roleName));
      const updated = items.some((i) => i.operation === "admin.update_user" && containsText(i, sub));
      return created && updated;
    });
    await poll("issues chưa có DevError", 20_000, async () => {
      const data = okData(await call("GET", issues, { token }), issues);
      expect(data?.enabled === true, `list_issues enabled=${data?.enabled}`);
      return ((data.items ?? []) as unknown[]).some((i) => containsText(i, "DevError"));
    });
  });

  step("system.status (superadmin)", async () => {
    okData(await call("GET", "/system/status", { token: need(ctx.admin, "phiên superadmin").access }), "system/status");
  });

  const password = process.env.SEED_PASSWORD || "password123";
  const adminToken = () => need(ctx.admin, "phiên superadmin").access;
  const agentSockets: Socket[] = [];
  addAgentSteps({ step, call, connect, ip, run, password, sockets: agentSockets, adminToken, mongo: opts.expectMongo });
  addRouterSteps({ step, call, connect, ip, run, password, sockets: agentSockets, adminToken });
  plan.push({ name: "đóng socket agent", fn: async () => agentSockets.forEach((x) => x.close()) });

  addPwaSteps({ step, call, base: opts.base });

  const tenantSockets: Socket[] = [];
  const otherSocket = () => need(ctx.socket, "socket user tenant default");
  addTenantSteps({ step, call, connect, ip, run, adminToken, otherSocket, password, sockets: tenantSockets });
  plan.push({ name: "đóng socket tenant", fn: async () => tenantSockets.forEach((x) => x.close()) });

  step("khoá user → socket bị ngắt, token cũ bị từ chối (REST 2103 + websocket)", async () => {
    const token = need(ctx.admin, "phiên superadmin").access;
    const target = need(ctx.target, "phiên user");
    const kicked = waitEvent(need(ctx.socket, "socket"), ["core:account_disabled", "disconnect"]);
    okData(await call("POST", "/admin/update_user", { body: { user_id: target.sub, is_active: false }, token }), "admin/update_user (khoá)");
    await kicked;
    const me = await call("GET", "/auth/me", { token: target.access });
    expect(me.status === 403 && me.body?.code === 2103, `auth/me bằng token cũ → ${dump(me)} — mong đợi 403 / 2103`);
    await expectRefused(target.access);
  });
}

let failed = false;
let ran = 0;
for (const s of plan) {
  if (!s.fn) {
    console.log(`– ${s.name} (bỏ qua: ${s.skip})`);
    continue;
  }
  try {
    await s.fn();
    ran++;
    console.log(`✓ ${s.name}`);
  } catch (err) {
    failed = true;
    console.log(`✗ ${s.name}\n    ${(err as Error).message}`);
    break; // bước sau phụ thuộc bước trước
  }
}
ctx.socket?.close();
console.log(failed ? "SMOKE HỎNG" : `SMOKE OK (profile=${opts.profile}, mongo=${opts.expectMongo}, ${ran} bước, run=${run})`);
process.exit(failed ? 1 : 0);
