import { PanelLeft, PanelLeftClose } from "lucide-react";
import { useMemo } from "react";

import { useCurrentUser } from "@/lib/auth/permissions";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { useUiStore } from "@/stores/ui.store";
import { Button } from "@/ui";

import { BrandLockup, BrandMark } from "./Brand";
import { buildNav } from "./nav";
import { SidebarGroup, SidebarLink } from "./SidebarLinks";

/** Sidebar cố định chỉ từ `md`; dưới `md` dùng thanh tab dưới + menu người dùng. */
export function Sidebar() {
  const t = useT();
  const user = useCurrentUser();
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggle = useUiStore((s) => s.toggleSidebar);
  const sections = useMemo(() => buildNav(user), [user]);
  return (
    <aside
      data-testid="sidebar"
      className={cn(
        "hidden shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 md:flex",
        collapsed ? "w-[4.5rem]" : "w-60",
      )}
    >
      <div className={cn("flex h-16 shrink-0 items-center px-4", collapsed && "justify-center px-0")}>
        {collapsed ? <BrandMark className="h-9 w-9" /> : <BrandLockup className="h-9" />}
      </div>
      <nav aria-label={t("nav.menu")} className="scrollbar-none flex-1 overflow-y-auto px-3 py-2">
        {sections.map((section) => (
          <div key={section.key} className="mb-3">
            {!collapsed && <div className="px-3 pb-1 pt-2 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{t(section.label)}</div>}
            <div className="space-y-0.5">
              {section.items.map((item) => (
                <SidebarLink key={item.to} item={item} collapsed={collapsed} />
              ))}
              {section.groups?.map((group) => (
                <SidebarGroup key={group.key} group={group} collapsed={collapsed} />
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className={cn("border-t border-sidebar-border p-3", collapsed && "px-2")}>
        <Button variant="ghost" size={collapsed ? "icon" : "sm"} onClick={toggle} aria-label={t("nav.collapse")} className={cn("text-muted-foreground", !collapsed && "w-full justify-start")}>
          {collapsed ? <PanelLeft className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
          {!collapsed && <span>{t("nav.collapse")}</span>}
        </Button>
      </div>
    </aside>
  );
}
