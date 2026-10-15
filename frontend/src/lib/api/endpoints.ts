/**
 * Bảng operation → method: path = tên đổi "." thành "/". Kiểu input / output của từng operation
 * lấy từ schema.d.ts sinh bằng openapi-typescript (R7) — tra theo path kết thúc bằng "/<miền>/<việc>".
 */
import type { paths } from "./schema";

export type Method = "GET" | "POST";

export const ENDPOINTS = {
  "auth.register": "POST",
  "auth.login": "POST",
  "auth.refresh": "POST",
  "auth.logout": "POST",
  "auth.logout_all": "POST",
  "auth.me": "GET",
  "auth.update_me": "POST",
  "auth.change_password": "POST",
  "auth.request_verify": "POST",
  "auth.verify_email": "POST",
  "auth.forgot_password": "POST",
  "auth.reset_password": "POST",
  // tenant (D10–D12) + mail (D14)
  "tenant.get": "GET",
  "tenant.update": "POST",
  "tenant.invite": "POST",
  "tenant.list_invites": "GET",
  "tenant.revoke_invite": "POST",
  "invites.preview": "GET",
  "tenants.list": "GET",
  "tenants.create": "POST",
  "tenants.update": "POST",
  "tenants.suspend": "POST",
  "tenants.resume": "POST",
  "mail.outbox": "GET",
  // module mẫu Tasks
  "tasks.list": "GET",
  "tasks.get": "GET",
  "tasks.summary": "GET",
  "tasks.people": "GET",
  "tasks.create": "POST",
  "tasks.update": "POST",
  "tasks.assign": "POST",
  "tasks.set_status": "POST",
  "tasks.delete": "POST",
  "tasks.add_comment": "POST",
  "admin.list_users": "GET",
  "admin.get_user": "GET",
  "admin.update_user": "POST",
  "admin.reset_password": "POST",
  "admin.user_policies": "GET",
  "admin.set_user_policies": "POST",
  "rbac.list_permissions": "GET",
  "rbac.list_roles": "GET",
  "rbac.create_role": "POST",
  "rbac.update_role": "POST",
  "rbac.delete_role": "POST",
  "rbac.set_role_policies": "POST",
  "notifications.list": "GET",
  "notifications.unread_count": "GET",
  "notifications.mark_read": "POST",
  "notifications.mark_all_read": "POST",
  "notifications.send_test": "POST",
  "push.config": "GET",
  "push.subscribe": "POST",
  "push.unsubscribe": "POST",
  "system.public_info": "GET",
  "system.get_settings": "GET",
  "system.update_settings": "POST",
  "system.status": "GET",
  "observability.list_events": "GET",
  "observability.list_issues": "GET",
  "observability.get_issue": "GET",
  "observability.set_issue_status": "POST",
  // trợ lý (chat), Agent Studio, credential, trace, usage
  "agent.list_agents": "GET",
  "agent.send": "POST",
  "agent.current_session": "GET",
  "agent.list_sessions": "GET",
  "agent.get_session": "GET",
  "agent.rename_session": "POST",
  "agent.delete_session": "POST",
  "agent.cancel": "POST",
  "agent.decide_approval": "POST",
  "agent.decide_approvals": "POST",
  "agent.chat_limits": "GET",
  "agent.run_events": "GET",
  "credentials.list": "GET",
  "credentials.create": "POST",
  "credentials.update": "POST",
  "credentials.delete": "POST",
  "studio.list_providers": "GET",
  "studio.save_provider": "POST",
  "studio.delete_provider": "POST",
  "studio.test_provider": "POST",
  "studio.provider_models": "GET",
  "studio.add_models": "POST",
  "studio.list_models": "GET",
  "studio.save_model": "POST",
  "studio.delete_model": "POST",
  "studio.list_agents": "GET",
  "studio.get_agent": "GET",
  "studio.save_agent": "POST",
  "studio.set_agent_keys": "POST",
  "studio.set_agent_limits": "POST",
  "studio.set_user_limit": "POST",
  "studio.set_toolsets": "POST",
  "studio.set_tool_override": "POST",
  "studio.tool_catalog": "GET",
  "studio.list_hooks": "GET",
  "studio.save_hook": "POST",
  "studio.delete_hook": "POST",
  "studio.test_hook": "POST",
  "studio.get_persona": "GET",
  "studio.save_persona": "POST",
  "studio.list_routes": "GET",
  "studio.save_route": "POST",
  "studio.delete_route": "POST",
  "traces.list": "GET",
  "traces.get": "GET",
  "traces.raw": "GET",
  "usage.summary": "GET",
  "usage.errors": "GET",
  "studio.configure_all": "POST",
  "studio.list_chat_blocks": "GET",
  "studio.block_chat": "POST",
  "studio.unblock_chat": "POST",
} as const satisfies Record<string, Method>;

export type OpName = keyof typeof ENDPOINTS;

/** Route tay (`ui_only`) — trình duyệt đi thẳng tới, không phải lời gọi dữ liệu. */
export const GOOGLE_AUTHORIZE_PATH = "auth/google/authorize";

export function endpoint(op: OpName): { method: Method; path: string } {
  return { method: ENDPOINTS[op], path: op.replace(".", "/") };
}

type OpPath<O extends string> = O extends `${infer D}.${infer A}` ? `${D}/${A}` : never;
type PathKey<O extends OpName> = Extract<keyof paths, `${string}/${OpPath<O>}`>;
type Spec<O extends OpName> = paths[PathKey<O>] extends infer P
  ? P extends Record<Lowercase<(typeof ENDPOINTS)[O]>, infer S>
    ? NonNullable<S>
    : never
  : never;
type JsonOf<T> = T extends { content: { "application/json": infer J } } ? J : never;
type QueryOf<S> = S extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;
type BodyOf<S> = S extends { requestBody?: infer B } ? JsonOf<NonNullable<B>> : never;
type OkOf<S> = S extends { responses: { 200: infer R } } ? JsonOf<R> : never;

export type OpInput<O extends OpName> = (typeof ENDPOINTS)[O] extends "GET" ? QueryOf<Spec<O>> : BodyOf<Spec<O>>;
export type OpOutput<O extends OpName> =
  OkOf<Spec<O>> extends { data?: infer D } ? ([NonNullable<D>] extends [never] ? null : NonNullable<D>) : never;
export type OpArgs<O extends OpName> = [OpInput<O>] extends [never]
  ? []
  : Partial<OpInput<O>> extends OpInput<O>
    ? [input?: OpInput<O>]
    : [input: OpInput<O>];
