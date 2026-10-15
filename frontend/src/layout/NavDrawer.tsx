import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Menu, Smartphone, X } from "lucide-react";
import { useMemo, useState } from "react";

import { useCurrentUser } from "@/lib/auth/permissions";
import { useT } from "@/lib/i18n";
import { isStandalone } from "@/lib/pwa";
import { useUiStore } from "@/stores/ui.store";
import { Button } from "@/ui";

import { BrandLockup } from "./Brand";
import { buildNav } from "./nav";
import { SidebarGroup, SidebarLink } from "./SidebarLinks";

/** Điện thoại: nút ☰ ở Header mở ngăn kéo trái chứa toàn bộ menu như sidebar desktop + hướng dẫn
 *  thêm vào màn hình chính. Bấm một mục → đóng ngăn kéo. */
export function NavDrawer() {
  const t = useT();
  const user = useCurrentUser();
  const [open, setOpen] = useState(false);
  const setInstallGuide = useUiStore((s) => s.setInstallGuide);
  const sections = useMemo(() => buildNav(user), [user]);
  const then = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };
  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Trigger asChild>
        <button type="button" aria-label={t("nav.openMenu")} data-testid="nav-open" className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-foreground hover:bg-accent md:hidden">
          <Menu className="h-6 w-6" />
        </button>
      </DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 md:hidden" />
        <DialogPrimitive.Content
          data-testid="nav-drawer"
          aria-describedby={undefined}
          className="fixed inset-y-0 left-0 z-50 flex w-[min(20rem,85vw)] flex-col border-r border-sidebar-border bg-sidebar pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)] text-sidebar-foreground shadow-card md:hidden"
        >
          <div className="flex h-14 shrink-0 items-center justify-between px-4">
            <BrandLockup className="h-8" />
            <DialogPrimitive.Close asChild>
              <button type="button" aria-label={t("nav.closeMenu")} className="grid h-11 w-11 place-items-center rounded-xl hover:bg-sidebar-accent">
                <X className="h-5 w-5" />
              </button>
            </DialogPrimitive.Close>
          </div>
          <DialogPrimitive.Title className="sr-only">{t("nav.menu")}</DialogPrimitive.Title>
          <nav
            aria-label={t("nav.menu")}
            className="scrollbar-none flex-1 overflow-y-auto overscroll-contain px-3 py-2"
            onClick={(e) => {
              if ((e.target as HTMLElement).closest("a")) setOpen(false);
            }}
          >
            {sections.map((section) => (
              <div key={section.key} className="mb-3">
                <div className="px-3 pb-1 pt-2 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{t(section.label)}</div>
                <div className="space-y-0.5">
                  {section.items.map((item) => (
                    <SidebarLink key={item.to} item={item} collapsed={false} />
                  ))}
                  {section.groups?.map((group) => (
                    <SidebarGroup key={group.key} group={group} collapsed={false} />
                  ))}
                </div>
              </div>
            ))}
          </nav>
          {!isStandalone() && (
            <div className="border-t border-sidebar-border p-3">
              <Button variant="ghost" className="w-full justify-start" data-testid="drawer-install" onClick={then(() => setInstallGuide(true))}>
                <Smartphone className="h-5 w-5" />
                {t("pwa.addToHome")}
              </Button>
            </div>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
