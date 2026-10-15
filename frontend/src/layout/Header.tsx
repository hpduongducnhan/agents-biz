import { cn } from "@/lib/cn";
import { usePageMeta } from "@/stores/ui.store";
import { PageHeaderSlot } from "@/ui";

import { BrandMark } from "./Brand";
import { NavDrawer } from "./NavDrawer";
import { NotificationBell } from "./NotificationBell";
import { SocketDot } from "./SocketDot";
import { LanguageToggle, ThemeToggle } from "./Toggles";
import { UserMenu } from "./UserMenu";

/** Dưới md: ☰ menu (ngăn kéo) · logo · tiêu đề (cắt) · đèn socket · chuông · avatar. Từ md: thêm ngôn ngữ + theme
 *  (logo + menu ở sidebar). */
export function Header() {
  const title = usePageMeta((s) => s.title);
  const subtitle = usePageMeta((s) => s.subtitle);
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background/90 px-2 backdrop-blur-md md:h-16 md:gap-3 md:px-6">
      <NavDrawer />
      <span className="shrink-0 md:hidden">
        <span data-testid="header-logo" className="block">
          <BrandMark className="h-8 w-8" />
        </span>
      </span>
      <div className="@container min-w-0 flex-1">
        <h1 className="truncate font-display text-base font-extrabold leading-tight md:text-lg" data-testid="page-title">
          {title}
        </h1>
        <div className="flex min-w-0 items-center gap-1.5">
          {subtitle && <p className="hidden min-w-0 truncate text-xs leading-tight text-muted-foreground sm:block">{subtitle}</p>}
          <PageHeaderSlot className={cn("hidden @min-[8rem]:not-empty:flex", subtitle && "before:content-['·']")} />
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-0.5 md:gap-2">
        <SocketDot />
        <NotificationBell />
        <div className="hidden items-center gap-2 md:flex" data-testid="header-tools">
          <LanguageToggle />
          <ThemeToggle />
        </div>
        <UserMenu />
      </div>
    </header>
  );
}
