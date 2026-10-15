import {
  Activity,
  Building,
  Building2,
  Inbox,
  Bell,
  Bot,
  Bug,
  Coins,
  Cpu,
  Gauge,
  LayoutDashboard,
  type LucideIcon,
  ScrollText,
  Settings2,
  ShieldBan,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Users,
  Waypoints,
} from "lucide-react";

import { canUseAssistant, hasPermission, PERMS } from "@/lib/auth/permissions";
import { moduleNav } from "@/modules/access";
import type { Me } from "@/lib/auth/types";

/** `id` cố định → data-testid `nav-<id>` (sidebar desktop + ngăn kéo điện thoại). */
export type NavEntry = { id: string; to: string; label: string; icon: LucideIcon; end?: boolean };
/** Nhóm con gập / mở trong một section — `key` → data-testid `nav-group-<key>`, trạng thái mở nhớ ở `ui.store`. */
export type NavGroup = { key: "observability" | "config" | "ai"; label: string; icon: LucideIcon; items: NavEntry[] };
export type NavSection = {
  key: "main" | "account" | "admin" | "sa";
  label: string;
  items: NavEntry[];
  groups?: NavGroup[];
};

/** Mọi mục của section, kể cả trong nhóm con. */
export function sectionEntries(section: NavSection): NavEntry[] {
  return [...section.items, ...(section.groups ?? []).flatMap((g) => g.items)];
}

/** Mục ứng với đường dẫn hiện tại (trùng hoặc là trang con) — nhóm chứa nó tự mở. */
export function isActiveEntry(entry: NavEntry, pathname: string): boolean {
  return entry.end ? pathname === entry.to : pathname === entry.to || pathname.startsWith(`${entry.to}/`);
}

/** Mục chính (section "Chính" của sidebar / ngăn kéo điện thoại): Tổng quan · mục của module (registry — D25) · Trợ lý.
 *  Điện thoại: Trợ lý còn nằm ở cụm nút nổi `MobileDock`. */
export const MAIN: NavEntry[] = [
  { id: "overview", to: "/", label: "nav.overview", icon: LayoutDashboard, end: true },
  { id: "assistant", to: "/assistant", label: "nav.assistant", icon: Bot },
];

/** Tổng quan → mục của module (registry — D25) → Trợ lý (khi được dùng). */
function mainEntries(user: Me | null): NavEntry[] {
  const [overview, assistant] = MAIN as [NavEntry, NavEntry];
  return [overview, ...moduleNav(user), ...(canUseAssistant(user) ? [assistant] : [])];
}

export function buildNav(user: Me | null): NavSection[] {
  const admin: NavEntry[] = [];
  if (hasPermission(user, PERMS.USER_VIEW)) admin.push({ id: "users", to: "/admin/users", label: "nav.users", icon: Users });
  if (hasPermission(user, PERMS.USER_VIEW)) admin.push({ id: "roles", to: "/admin/roles", label: "nav.roles", icon: ShieldCheck });
  const sa: NavGroup[] = user?.is_superadmin
    ? [
        {
          key: "observability",
          label: "nav.group.observability",
          icon: Gauge,
          items: [
            { id: "status", to: "/sa/status", label: "nav.status", icon: Activity },
            { id: "events", to: "/sa/events", label: "nav.events", icon: ScrollText },
            { id: "issues", to: "/sa/issues", label: "nav.issues", icon: Bug },
            { id: "mail", to: "/sa/mail", label: "nav.mail", icon: Inbox },
          ],
        },
        {
          key: "config",
          label: "nav.group.config",
          icon: SlidersHorizontal,
          items: [
            { id: "settings", to: "/sa/settings", label: "nav.settings", icon: Settings2 },
            { id: "tenants", to: "/sa/tenants", label: "nav.tenants", icon: Building2 },
          ],
        },
        {
          key: "ai",
          label: "nav.group.ai",
          icon: Sparkles,
          items: [
            { id: "studio", to: "/studio", label: "nav.studio", icon: Cpu },
            { id: "traces", to: "/sa/traces", label: "nav.traces", icon: Waypoints },
            { id: "usage", to: "/sa/usage", label: "nav.usage", icon: Coins },
            { id: "chat-guard", to: "/sa/chat-guard", label: "nav.chatGuard", icon: ShieldBan },
            { id: "ai-settings", to: "/sa/ai-settings", label: "nav.aiSettings", icon: Settings2 },
          ],
        },
      ]
    : [];
  const sections: NavSection[] = [
    { key: "main", label: "nav.group.main", items: mainEntries(user) },
    {
      key: "account",
      label: "nav.group.account",
      items: [
        { id: "notifications", to: "/notifications", label: "nav.notifications", icon: Bell },
        { id: "org", to: "/org", label: "nav.org", icon: Building },
        { id: "profile", to: "/profile", label: "nav.profile", icon: UserRound },
      ],
    },
    { key: "admin", label: "nav.group.admin", items: admin },
    { key: "sa", label: "nav.group.sa", items: [], groups: sa },
  ];
  return sections.filter((s) => sectionEntries(s).length > 0);
}
