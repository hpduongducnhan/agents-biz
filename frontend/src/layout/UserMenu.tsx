import { Check, Download, LogOut, Smartphone, UserRound } from "lucide-react";
import { useNavigate } from "react-router";

import { authApi } from "@/features/auth/api";
import { getRefreshToken } from "@/lib/auth-tokens";
import { useAuthStore } from "@/lib/auth/store";
import { useLocaleStore, useT } from "@/lib/i18n";
import { disablePush } from "@/lib/push";
import { installPwa, isStandalone, usePwaStore } from "@/lib/pwa";
import { useUiStore } from "@/stores/ui.store";
import { Avatar, AvatarFallback, Badge, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/ui";

import { LOCALES, THEMES, themeIcon, useChangeLocale } from "./Toggles";

export function initials(name: string, email: string): string {
  const source = name.trim() || email;
  return (
    source
      .split(/\s+/)
      .filter(Boolean)
      .slice(-2)
      .map((p) => p[0]?.toUpperCase())
      .join("") || "?"
  );
}

export function UserMenu() {
  const t = useT();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const canInstall = usePwaStore((s) => !!s.prompt);
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const locale = useLocaleStore((s) => s.locale);
  const changeLocale = useChangeLocale();
  const openGuide = useUiStore((s) => s.setInstallGuide);
  if (!user) return null;

  const handleLogout = async () => {
    await disablePush().catch(() => undefined); // máy này thôi nhận thông báo của tài khoản
    const refresh = getRefreshToken();
    if (refresh) await authApi.logout(refresh).catch(() => undefined); // phiên cục bộ vẫn xoá dù API lỗi
    logout();
    void navigate("/login", { replace: true });
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label={t("nav.account")} data-testid="user-menu" className="grid h-11 w-11 shrink-0 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring md:h-9 md:w-9">
          <Avatar className="h-9 w-9 md:h-8 md:w-8">
            <AvatarFallback className="bg-brand-muted text-xs font-bold text-brand">{initials(user.name, user.email)}</AvatarFallback>
          </Avatar>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[min(18rem,calc(100vw-1.5rem))]">
        <div className="min-w-0 px-2 py-1.5">
          <div data-testid="user-menu-name" className="truncate text-sm font-bold">
            {user.name || user.email}
          </div>
          {user.tenant && (
            <div data-testid="user-menu-tenant" className="truncate text-xs font-semibold text-brand">
              {user.tenant.name}
            </div>
          )}
          <div data-testid="user-menu-email" className="break-all text-xs text-muted-foreground">
            {user.email}
          </div>
          {user.is_superadmin && <Badge className="mt-1.5">{t("nav.superadmin")}</Badge>}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem data-testid="menu-profile" onSelect={() => void navigate("/profile")}>
          <UserRound className="mr-2 h-4 w-4" />
          {t("nav.profile")}
        </DropdownMenuItem>
        <DropdownMenuSeparator className="md:hidden" />
        <div className="px-2 py-1 text-xs font-bold text-muted-foreground md:hidden">{t("action.theme")}</div>
        {THEMES.map((th) => {
          const Icon = themeIcon[th];
          return (
            <DropdownMenuItem key={th} className="md:hidden" onSelect={() => setTheme(th)}>
              <Icon className="mr-2 h-4 w-4" />
              <span className="flex-1">{t(`theme.${th}`)}</span>
              {theme === th && <Check className="h-4 w-4" />}
            </DropdownMenuItem>
          );
        })}
        <div className="px-2 py-1 text-xs font-bold text-muted-foreground md:hidden">{t("action.language")}</div>
        {LOCALES.map((l) => (
          <DropdownMenuItem key={l} className="md:hidden" onSelect={() => changeLocale(l)}>
            <span className="mr-2 w-4 text-center text-[11px] font-bold">{l.toUpperCase()}</span>
            <span className="flex-1">{t(`lang.${l}`)}</span>
            {locale === l && <Check className="h-4 w-4" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        {!isStandalone() && (
          <DropdownMenuItem className="md:hidden" onSelect={() => openGuide(true)} data-testid="menu-install-guide">
            <Smartphone className="mr-2 h-4 w-4" />
            {t("pwa.addToHome")}
          </DropdownMenuItem>
        )}
        {canInstall ? (
          <DropdownMenuItem className="hidden md:flex" onSelect={() => void installPwa()} data-testid="menu-install">
            <Download className="mr-2 h-4 w-4" />
            {t("pwa.install")}
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem onSelect={() => void handleLogout()} className="text-destructive focus:text-destructive" data-testid="logout">
          <LogOut className="mr-2 h-4 w-4" />
          {t("action.logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
