/** API tenant (D10–D12) + hộp thư console (D14) — tên op khớp backend; kiểu từ OpenAPI (R7). */
import { call, type OpInput, type OpOutput } from "@/lib/api";

export type Tenant = OpOutput<"tenant.get">;
export type Invite = OpOutput<"tenant.list_invites">[number];
export type InvitePreview = OpOutput<"invites.preview">;
export type TenantPolicies = Tenant["policies"];
export type TenantsQuery = OpInput<"tenants.list">;
export type OutboxItem = OpOutput<"mail.outbox">["items"][number];

export const tenantApi = {
  current: () => call("tenant.get"),
  rename: (name: string) => call("tenant.update", { name }),
  invite: (input: OpInput<"tenant.invite">) => call("tenant.invite", input),
  invites: () => call("tenant.list_invites"),
  revokeInvite: (invite_id: string) => call("tenant.revoke_invite", { invite_id }),
  preview: (token: string) => call("invites.preview", { token }),
};

export const tenantsApi = {
  list: (q: TenantsQuery) => call("tenants.list", q),
  create: (input: OpInput<"tenants.create">) => call("tenants.create", input),
  update: (input: OpInput<"tenants.update">) => call("tenants.update", input),
  suspend: (tenant_id: string) => call("tenants.suspend", { tenant_id }),
  resume: (tenant_id: string) => call("tenants.resume", { tenant_id }),
};

export const mailApi = {
  outbox: (limit = 50) => call("mail.outbox", { limit }),
};
