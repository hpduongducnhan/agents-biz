/** Dữ liệu giả cho test — kiểu lấy từ hợp đồng OpenAPI nên lệch shape là typecheck đỏ. */
import type { AdminUser } from "@/features/admin/api";
import type { EventEntry, Issue, IssueDetail } from "@/features/observability/api";
import type { LoginResult } from "@/lib/auth/types";
import type { Me } from "@/lib/auth/types";
import type { Notification } from "@/features/notifications/api";
import type { OpOutput } from "@/lib/api";
import type { PublicInfo } from "@/features/system/api";
import type { Role } from "@/features/rbac/api";
import type { SystemSettings } from "@/features/system/api";
import type { Invite, Tenant } from "@/features/tenant/api";

export function me(over: Partial<Me> = {}): Me {
  return {
    id: "u1",
    email: "u1@test.local",
    name: "Người Dùng Một",
    timezone: "Asia/Ho_Chi_Minh",
    locale: "vi",
    is_active: true,
    is_superadmin: false,
    must_change_password: false,
    has_password: true,
    email_verified: true,
    tenant: { id: "t1", name: "Tổ chức Một", slug: "to-chuc-mot", agent_enabled: true },
    roles: [{ id: "r-member", name: "member" }],
    permissions: ["agent.chat", "agent.lookup"],
    created_at: "2026-10-01T00:00:00Z",
    last_login_at: null,
    ...over,
  };
}

export function notification(over: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    kind: "test",
    title: "Thông báo thử",
    body: "",
    params: {},
    action: null,
    read_at: null,
    created_at: "2026-10-12T00:00:00Z",
    ...over,
  };
}

export function loginResult(user: Me = me()): LoginResult {
  return { user, tokens: { access_token: "a1", refresh_token: "r1", token_type: "bearer", expires_in: 1800 }, verification_sent: false };
}

export function publicInfo(over: Partial<PublicInfo> = {}): PublicInfo {
  return { name: "BizWithAgents", version: "dev", signup_open: true, signup_mode: "default_tenant", email_verification: "soft", google_enabled: false, ...over };
}

export function page<T>(items: T[], total = items.length) {
  return { items, total, limit: 20, offset: 0 };
}

export function adminUser(over: Partial<AdminUser> = {}): AdminUser {
  return {
    id: "u2",
    email: "u2@test.local",
    name: "Người Dùng Hai",
    timezone: "Asia/Ho_Chi_Minh",
    locale: "vi",
    is_active: true,
    is_superadmin: false,
    must_change_password: false,
    has_password: true,
    email_verified: true,
    tenant: { id: "t1", name: "Tổ chức Một", slug: "to-chuc-mot", agent_enabled: true },
    roles: [{ id: "r-member", name: "member" }],
    created_at: "2026-10-01T00:00:00Z",
    last_login_at: null,
    ...over,
  };
}

export function role(over: Partial<Role> = {}): Role {
  return { id: "r-member", name: "member", description: "Thành viên", is_builtin: true, permissions: ["agent.chat", "agent.lookup"], user_count: 3, policies: {}, ...over };
}

export function statusOut(over: Partial<OpOutput<"system.status">> = {}): OpOutput<"system.status"> {
  return {
    version: "abc123",
    env: "dev",
    mongo_enabled: true,
    ready: true,
    checks: { "postgres.rw": "ok", "redis.rw": "ok", rabbitmq: "ok", "mongo.rw": "ok" },
    pipeline_ok: true,
    pipeline: { consume: { last: "2026-10-12T00:00:00Z", age_s: 3, ok: true } },
    observability: { enabled: true, queued: 0, written: 12, dropped: 0, failed: 0, open_issues: 1, open_issues_error: null },
    settings_defaults: ["event_log_ttl_days"],
    time: "2026-10-12T00:00:00Z",
    ...over,
  };
}

export function settingsOut(over: Partial<SystemSettings> = {}): SystemSettings {
  return {
    signup_mode: "default_tenant",
    email_verification: "soft",
    user_limit_default: 0,
    google_enabled: false,
    chat_history_limit: 20,
    chat_history_tools: true,
    chat_stream: true,
    chat_stream_flush_ms: 50,
    chat_session_idle_min: 30,
    event_log_ttl_days: 180,
    span_ttl_days: 90,
    raw_http_ttl_days: 7,
    chat_per_minute: 10,
    chat_per_hour: 100,
    chat_per_day: 400,
    chat_autoblock: true,
    chat_autoblock_strikes: 5,
    chat_autoblock_window_min: 10,
    chat_autoblock_minutes: 30,
    google_configured: false,
    defaults_applied: ["event_log_ttl_days"],
    ...over,
  };
}

export const FP = "0123456789abcdef0123456789abcdef01234567";

export function eventItem(over: Partial<EventEntry> = {}): EventEntry {
  return {
    id: "e1",
    ts: "2026-10-12T01:02:03Z",
    cid: "cid-e1",
    actor_id: "11111111-1111-1111-1111-111111111111",
    actor_kind: "user",
    is_superadmin: false,
    source: "web",
    agent_run_id: null,
    agent_slug: null,
    operation: "admin.update_user",
    effect: "write",
    input: { user_id: "u2", is_active: false },
    ok: true,
    error_code: null,
    duration_ms: 12,
    expire_at: "2027-04-10T01:02:03Z",
    ...over,
  };
}

export function issueSummary(over: Partial<Issue> = {}): Issue {
  return {
    fingerprint: FP,
    title: "ZeroDivisionError: division by zero",
    exc_type: "ZeroDivisionError",
    loc: "exc0001",
    source: "http",
    status: "open",
    count: 3,
    first_seen: "2026-10-11T00:00:00Z",
    last_seen: "2026-10-12T00:00:00Z",
    status_changed_at: null,
    status_changed_by: null,
    sample: { cid: "cid-i1", source: "http", operation: "system.status", path: null, user_id: null, context: {} },
    ...over,
  };
}

export function issueRecord(over: Partial<IssueDetail> = {}): IssueDetail {
  const base = issueSummary();
  return {
    ...base,
    sample: { ...base.sample, context: { query: { a: 1 } }, traceback: "Traceback (most recent call last):\n  File \"app/x.py\", line 1" },
    recent: [{ cid: "cid-r1", ts: "2026-10-12T00:00:00Z" }],
    ...over,
  };
}

export function tenant(over: Partial<Tenant> = {}): Tenant {
  return {
    id: "t1",
    name: "Tổ chức Một",
    slug: "to-chuc-mot",
    status: "active",
    user_count: 3,
    user_limit: 10,
    policies: {},
    created_at: "2026-10-01T00:00:00Z",
    ...over,
  };
}

export function invite(over: Partial<Invite> = {}): Invite {
  return {
    id: "i1",
    email: "m***@test.local",
    role: { id: "r-member", name: "member" },
    uses: 0,
    max_uses: 1,
    expires_at: "2026-10-22T00:00:00Z",
    created_at: "2026-10-15T00:00:00Z",
    link: null,
    ...over,
  };
}
