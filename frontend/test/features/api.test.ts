// @vitest-environment jsdom
import { QueryClient } from "@tanstack/react-query";
import type { AxiosAdapter } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { adminApi } from "@/features/admin/api";
import { ADMIN } from "@/features/admin/keys";
import { authApi } from "@/features/auth/api";
import { AUTH } from "@/features/auth/keys";
import { markReadFast, notificationsApi } from "@/features/notifications/api";
import { NOTIF } from "@/features/notifications/keys";
import { obsApi } from "@/features/observability/api";
import { OBS } from "@/features/observability/keys";
import { rbacApi } from "@/features/rbac/api";
import { RBAC } from "@/features/rbac/keys";
import { systemApi } from "@/features/system/api";
import { SYSTEM } from "@/features/system/keys";
import { configureHttp } from "@/lib/api";
import { tasksApi } from "@/modules/tasks/api";
import { TASKS } from "@/modules/tasks/keys";
import { socketManager } from "@/lib/realtime/socket";

type Seen = { method?: string; url?: string; params?: unknown; data?: unknown };
const seen: Seen[] = [];
const adapter: AxiosAdapter = async (cfg) => {
  seen.push({ method: cfg.method, url: cfg.url, params: cfg.params, data: cfg.data ? JSON.parse(String(cfg.data)) : undefined });
  return { data: { success: true, code: 0, message: "OK", data: {}, correlation_id: "c" }, status: 200, statusText: "", headers: {}, config: cfg };
};

beforeEach(() => {
  seen.length = 0;
  configureHttp({ baseURL: "http://t/api", adapter });
});

const FP = "0123456789abcdef0123456789abcdef01234567"; // fingerprint issue: sha1 hex 40

const cases: [string, () => Promise<unknown>, Seen][] = [
  ["auth.login", () => authApi.login({ email: "a@test.local", password: "password123" }), { method: "post", url: "auth/login", data: { email: "a@test.local", password: "password123" } }],
  ["auth.register", () => authApi.register({ email: "b@test.local", password: "password123", name: "B" }), { method: "post", url: "auth/register", data: { email: "b@test.local", password: "password123", name: "B" } }],
  ["auth.logout", () => authApi.logout("r1"), { method: "post", url: "auth/logout", data: { refresh_token: "r1" } }],
  ["auth.logout_all", () => authApi.logoutAll(), { method: "post", url: "auth/logout_all", data: {} }],
  ["auth.me", () => authApi.me(), { method: "get", url: "auth/me" }],
  ["auth.update_me", () => authApi.updateMe({ name: "C", timezone: "Asia/Ho_Chi_Minh", locale: "vi" }), { method: "post", url: "auth/update_me", data: { name: "C", timezone: "Asia/Ho_Chi_Minh", locale: "vi" } }],
  ["auth.change_password", () => authApi.changePassword({ current_password: "old-pass-1", new_password: "new-pass-1" }), { method: "post", url: "auth/change_password", data: { current_password: "old-pass-1", new_password: "new-pass-1" } }],
  ["admin.list_users", () => adminApi.listUsers({ q: "an", limit: 20, offset: 0 }), { method: "get", url: "admin/list_users", params: { q: "an", limit: 20, offset: 0 } }],
  ["admin.get_user", () => adminApi.getUser("u2"), { method: "get", url: "admin/get_user", params: { user_id: "u2" } }],
  ["admin.update_user", () => adminApi.updateUser({ user_id: "u2", role_ids: ["r1"] }), { method: "post", url: "admin/update_user", data: { user_id: "u2", role_ids: ["r1"] } }],
  ["admin.reset_password", () => adminApi.resetPassword({ user_id: "u2", new_password: "temp-pass-1" }), { method: "post", url: "admin/reset_password", data: { user_id: "u2", new_password: "temp-pass-1" } }],
  ["rbac.list_permissions", () => rbacApi.listPermissions(), { method: "get", url: "rbac/list_permissions" }],
  ["rbac.list_roles", () => rbacApi.listRoles(), { method: "get", url: "rbac/list_roles", params: { limit: 100, offset: 0 } }],
  ["rbac.create_role", () => rbacApi.createRole({ name: "Kế toán", description: "", permissions: ["user.view"] }), { method: "post", url: "rbac/create_role", data: { name: "Kế toán", description: "", permissions: ["user.view"] } }],
  ["rbac.update_role", () => rbacApi.updateRole({ role_id: "r9", permissions: [] }), { method: "post", url: "rbac/update_role", data: { role_id: "r9", permissions: [] } }],
  ["rbac.delete_role", () => rbacApi.deleteRole("r9"), { method: "post", url: "rbac/delete_role", data: { role_id: "r9" } }],
  ["notifications.list", () => notificationsApi.list({ unread_only: true, limit: 20, offset: 0 }), { method: "get", url: "notifications/list", params: { unread_only: true, limit: 20, offset: 0 } }],
  ["notifications.unread_count", () => notificationsApi.unreadCount(), { method: "get", url: "notifications/unread_count" }],
  ["notifications.mark_all_read", () => notificationsApi.markAllRead(), { method: "post", url: "notifications/mark_all_read", data: {} }],
  ["notifications.send_test", () => notificationsApi.sendTest({ email: "u1@test.local", title: "Xin chào" }), { method: "post", url: "notifications/send_test", data: { email: "u1@test.local", title: "Xin chào" } }],
  ["system.public_info", () => systemApi.publicInfo(), { method: "get", url: "system/public_info" }],
  ["system.get_settings", () => systemApi.getSettings(), { method: "get", url: "system/get_settings" }],
  ["system.update_settings", () => systemApi.updateSettings({ signup_mode: "invite_only" }), { method: "post", url: "system/update_settings", data: { signup_mode: "invite_only" } }],
  ["system.status", () => systemApi.status(), { method: "get", url: "system/status" }],
  ["observability.list_events", () => obsApi.listEvents({ source: "agent", limit: 20, offset: 0 }), { method: "get", url: "observability/list_events", params: { source: "agent", limit: 20, offset: 0 } }],
  ["observability.list_issues", () => obsApi.listIssues({ status: "open", limit: 20, offset: 0 }), { method: "get", url: "observability/list_issues", params: { status: "open", limit: 20, offset: 0 } }],
  ["observability.get_issue", () => obsApi.getIssue(FP), { method: "get", url: "observability/get_issue", params: { fingerprint: FP } }],
  ["observability.set_issue_status", () => obsApi.setIssueStatus(FP, "resolved"), { method: "post", url: "observability/set_issue_status", data: { fingerprint: FP, status: "resolved" } }],
  ["tasks.list", () => tasksApi.list({ open_only: true, limit: 20, offset: 0 }), { method: "get", url: "tasks/list", params: { open_only: true, limit: 20, offset: 0 } }],
  ["tasks.get", () => tasksApi.get("t1"), { method: "get", url: "tasks/get", params: { task_id: "t1" } }],
  ["tasks.summary", () => tasksApi.summary(), { method: "get", url: "tasks/summary" }],
  ["tasks.people", () => tasksApi.people({ q: "lan", limit: 100 }), { method: "get", url: "tasks/people", params: { q: "lan", limit: 100 } }],
  ["tasks.create", () => tasksApi.create({ title: "x" }), { method: "post", url: "tasks/create", data: { title: "x" } }],
  ["tasks.update", () => tasksApi.update({ task_id: "t1", due_at: null }), { method: "post", url: "tasks/update", data: { task_id: "t1", due_at: null } }],
  ["tasks.assign", () => tasksApi.assign("t1", null), { method: "post", url: "tasks/assign", data: { task_id: "t1", assignee_id: null } }],
  ["tasks.set_status", () => tasksApi.setStatus("t1", "done"), { method: "post", url: "tasks/set_status", data: { task_id: "t1", status: "done" } }],
  ["tasks.delete", () => tasksApi.remove("t1"), { method: "post", url: "tasks/delete", data: { task_id: "t1" } }],
  ["tasks.add_comment", () => tasksApi.comment("t1", "ok"), { method: "post", url: "tasks/add_comment", data: { task_id: "t1", body: "ok" } }],
];

describe("features/*/api — đúng method + path + payload theo hợp đồng", () => {
  it.each(cases)("%s", async (_op, run, want) => {
    await run();
    expect(seen).toEqual([{ params: undefined, data: undefined, ...want }]);
  });
});

describe("query key khớp `invalidates` của BE (data:changed theo tiền tố)", () => {
  it.each([
    ["auth.me", AUTH.me()],
    ["admin.users", ADMIN.users({ q: "an" })],
    ["admin.users", ADMIN.user("u2")],
    ["rbac.roles", RBAC.roles()],
    ["notifications", NOTIF.list({ limit: 20, offset: 0 })],
    ["notifications", NOTIF.unread()],
    ["system", SYSTEM.settings()],
    ["system", SYSTEM.publicInfo()],
    ["observability", OBS.issues({ status: "open" })],
    ["observability", OBS.issue(FP)],
    ["tasks.list", TASKS.list({ mine: true })],
    ["tasks.detail", TASKS.detail("t1")],
    ["tasks.summary", TASKS.summary()],
  ] as const)("%s là tiền tố của %j", (name, key) => {
    const prefix = name.split(".");
    expect(key.slice(0, prefix.length)).toEqual(prefix);
  });
});

describe("markReadFast", () => {
  it("socket đang nối → gửi ws, không gọi REST (kết quả về qua data:changed)", async () => {
    const send = vi.spyOn(socketManager, "send").mockResolvedValue({ accepted: true, cid: "c" });
    const qc = new QueryClient();
    const inv = vi.spyOn(qc, "invalidateQueries");
    await markReadFast(qc, ["n1"]);
    expect(send).toHaveBeenCalledWith("notifications.mark_read", { ids: ["n1"] });
    expect(seen).toEqual([]);
    expect(inv).not.toHaveBeenCalled();
  });

  it("socket offline → REST rồi tự làm mới danh sách", async () => {
    vi.spyOn(socketManager, "send").mockResolvedValue({ accepted: false, error: "offline" });
    const qc = new QueryClient();
    const inv = vi.spyOn(qc, "invalidateQueries");
    await markReadFast(qc, ["n1", "n2"]);
    expect(seen).toEqual([{ method: "post", url: "notifications/mark_read", params: undefined, data: { ids: ["n1", "n2"] } }]);
    expect(inv).toHaveBeenCalledWith({ queryKey: ["notifications"] });
  });
});
