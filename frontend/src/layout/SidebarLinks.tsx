import { ChevronDown } from "lucide-react";
import { NavLink, useLocation } from "react-router";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { useUiStore } from "@/stores/ui.store";

import { isActiveEntry, type NavEntry, type NavGroup } from "./nav";

export function SidebarLink({ item, collapsed, nested = false }: { item: NavEntry; collapsed: boolean; nested?: boolean }) {
  const t = useT();
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      data-testid={`nav-${item.id}`}
      aria-label={collapsed ? t(item.label) : undefined}
      className={({ isActive }) =>
        cn(
          "flex min-h-11 items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold transition-colors md:min-h-10",
          isActive ? "bg-brand-muted text-brand" : "text-sidebar-foreground hover:bg-sidebar-accent",
          collapsed && "justify-center px-0",
          nested && !collapsed && "md:min-h-9 md:py-1.5", // điện thoại (ngăn kéo): vẫn ≥ 44px — ui-system §7
        )
      }
    >
      <Icon className="h-5 w-5 shrink-0" aria-hidden />
      {!collapsed && <span className="truncate">{t(item.label)}</span>}
    </NavLink>
  );
}

/** Nhóm con gập / mở. Chưa chạm tay → mở khi chứa trang hiện tại; sidebar thu gọn → icon phẳng + vạch ngăn. */
export function SidebarGroup({ group, collapsed }: { group: NavGroup; collapsed: boolean }) {
  const t = useT();
  const { pathname } = useLocation();
  const stored = useUiStore((s) => s.navGroups[group.key]);
  const setNavGroup = useUiStore((s) => s.setNavGroup);
  const here = group.items.some((i) => isActiveEntry(i, pathname));
  const open = stored ?? here;
  const Icon = group.icon;
  if (collapsed)
    return (
      <div className="space-y-0.5 border-t border-sidebar-border pt-1 first:border-t-0 first:pt-0" data-testid={`nav-group-${group.key}`}>
        {group.items.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed />
        ))}
      </div>
    );
  return (
    <div>
      <button
        type="button"
        data-testid={`nav-group-${group.key}`}
        aria-expanded={open}
        onClick={() => setNavGroup(group.key, !open)}
        className={cn(
          "flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold transition-colors hover:bg-sidebar-accent md:min-h-10",
          here && !open ? "text-brand" : "text-sidebar-foreground",
        )}
      >
        <Icon className="h-5 w-5 shrink-0" aria-hidden />
        <span className="flex-1 truncate text-left">{t(group.label)}</span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="ml-5 space-y-0.5 border-l border-sidebar-border pl-2" data-testid={`nav-group-${group.key}-items`}>
          {group.items.map((item) => (
            <SidebarLink key={item.to} item={item} collapsed={false} nested />
          ))}
        </div>
      )}
    </div>
  );
}
