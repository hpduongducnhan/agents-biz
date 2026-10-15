import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, expectTypeOf, it } from "vitest";

import { MODULES } from "@/modules/registry";
import { ENDPOINTS, endpoint, type OpArgs, type OpInput, type OpName, type OpOutput } from "@/lib/api/endpoints";

type PathItem = Partial<Record<"get" | "post" | "put" | "patch" | "delete", unknown>>;
const spec = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../src/lib/api/openapi.json", import.meta.url)), "utf8"),
) as { paths: Record<string, PathItem> };

describe("hợp đồng REST với openapi.json (R7)", () => {
  it("mỗi operation có đúng một path kết thúc bằng /<miền>/<việc> với đúng method", () => {
    const problems: string[] = [];
    for (const op of Object.keys(ENDPOINTS) as OpName[]) {
      const { method, path } = endpoint(op);
      const hits = Object.keys(spec.paths).filter((p) => p.endsWith(`/${path}`));
      if (hits.length !== 1) {
        problems.push(`${op}: ${hits.length} path khớp /${path}`);
        continue;
      }
      const item = spec.paths[hits[0] as string];
      if (!item?.[method === "GET" ? "get" : "post"]) problems.push(`${op}: thiếu ${method} ${hits[0]}`);
    }
    expect(problems).toEqual([]);
  });

  it("op đọc là GET, mọi op còn lại là POST ", () => {
    const modules = new Set(MODULES.map((m) => m.id)); // op của module: method đã đối chiếu openapi.json ở test trên
    const gets = Object.entries(ENDPOINTS)
      .filter(([op, m]) => m === "GET" && !modules.has(op.split(".")[0] ?? ""))
      .map(([op]) => op)
      .sort();
    expect(gets).toEqual([
      "admin.get_user",
      "admin.list_users",
      "admin.user_policies",
      "agent.chat_limits",
      "agent.current_session",
      "agent.get_session",
      "agent.list_agents",
      "agent.list_sessions",
      "agent.run_events",
      "auth.me",
      "credentials.list",
      "invites.preview",
      "mail.outbox",
      "notifications.list",
      "notifications.unread_count",
      "observability.get_issue",
      "observability.list_events",
      "observability.list_issues",
      "push.config",
      "rbac.list_permissions",
      "rbac.list_roles",
      "studio.get_agent",
      "studio.get_persona",
      "studio.list_agents",
      "studio.list_chat_blocks",
      "studio.list_hooks",
      "studio.list_models",
      "studio.list_providers",
      "studio.list_routes",
      "studio.provider_models",
      "studio.tool_catalog",
      "system.get_settings",
      "system.public_info",
      "system.status",
      "tenant.get",
      "tenant.list_invites",
      "tenants.list",
      "traces.get",
      "traces.list",
      "traces.raw",
      "usage.errors",
      "usage.summary",
]);
  });

  it("Chống spam: chat_limits / list_chat_blocks là GET; block_chat / unblock_chat là POST", () => {
    expect(endpoint("agent.chat_limits")).toEqual({ method: "GET", path: "agent/chat_limits" });
    expect(endpoint("studio.list_chat_blocks")).toEqual({ method: "GET", path: "studio/list_chat_blocks" });
    expect(endpoint("studio.block_chat")).toEqual({ method: "POST", path: "studio/block_chat" });
    expect(endpoint("studio.unblock_chat")).toEqual({ method: "POST", path: "studio/unblock_chat" });
  });

  it("path = tên operation đổi dấu chấm thành gạch chéo", () => {
    expect(endpoint("admin.list_users")).toEqual({ method: "GET", path: "admin/list_users" });
    expect(endpoint("auth.login")).toEqual({ method: "POST", path: "auth/login" });
  });

  it("shape chính đúng kỳ vọng — lệch thì `make fe-typecheck` đỏ", () => {
    expectTypeOf<OpInput<"auth.login">>().toExtend<{ email: string; password: string }>();
    expectTypeOf<OpOutput<"auth.login">>().toExtend<{
      user: { id: string; email: string; email_verified: boolean; tenant?: { id: string; name: string } | null };
      tokens?: { access_token: string; refresh_token: string } | null;
      verification_sent: boolean;
    }>();
    expectTypeOf<OpOutput<"auth.me">>().toExtend<{
      id: string;
      email: string;
      name: string;
      is_superadmin: boolean;
      must_change_password: boolean;
      permissions: string[];
    }>();
    expectTypeOf<OpOutput<"admin.list_users">>().toExtend<{ items: unknown[]; total: number; limit: number; offset: number }>();
    expectTypeOf<OpOutput<"observability.list_events">>().toExtend<{ enabled: boolean; items: unknown[]; total: number }>();
    expectTypeOf<OpArgs<"auth.me">>().toEqualTypeOf<[]>();
  });
});
