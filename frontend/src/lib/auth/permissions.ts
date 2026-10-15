/** Quyền hệ thống — mirror catalog BE. Ẩn UI chỉ là UX; chặn thật ở guard + BE. */
import { useAuthStore } from "./store";
import type { Me } from "./types";

export const PERMS = {
  USER_VIEW: "user.view",
  USER_MANAGE: "user.manage",
  TENANT_INVITE: "tenant.invite",
  TENANT_SETTINGS: "tenant.settings",
  AGENT_CHAT: "agent.chat",
} as const;

export type Perm = string | readonly string[];

export function hasPermission(user: Me | null, perm?: Perm): boolean {
  if (!user) return false;
  if (!perm || (Array.isArray(perm) && perm.length === 0)) return true;
  if (user.is_superadmin) return true;
  const want: readonly string[] = typeof perm === "string" ? [perm] : perm;
  return want.some((p) => user.permissions.includes(p));
}

/** Được dùng trợ lý: có `agent.chat` và tổ chức không tắt trợ lý (`tenant.agent_enabled`); superadmin luôn được. */
export function canUseAssistant(user: Me | null): boolean {
  if (!user) return false;
  if (user.is_superadmin) return true;
  return user.tenant?.agent_enabled !== false && hasPermission(user, PERMS.AGENT_CHAT);
}

export function useCanUseAssistant(): boolean {
  return canUseAssistant(useAuthStore((s) => s.user));
}

export function useCurrentUser(): Me | null {
  return useAuthStore((s) => s.user);
}

export function useHasPermission(perm?: Perm): boolean {
  const user = useAuthStore((s) => s.user);
  return hasPermission(user, perm);
}

export function useIsSuperadmin(): boolean {
  return useAuthStore((s) => !!s.user?.is_superadmin);
}
