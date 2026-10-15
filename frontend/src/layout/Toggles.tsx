import { useMutation } from "@tanstack/react-query";
import { Monitor, Moon, Sun } from "lucide-react";

import { authApi } from "@/features/auth/api";
import { useAuthStore } from "@/lib/auth/store";
import { cn } from "@/lib/cn";
import { type Locale, useLocaleStore, useT } from "@/lib/i18n";
import { type Theme, useUiStore } from "@/stores/ui.store";
import { Button } from "@/ui";

export const themeIcon: Record<Theme, typeof Sun> = { system: Monitor, light: Sun, dark: Moon };
export const THEMES: Theme[] = ["light", "dark", "system"];
export const LOCALES: Locale[] = ["vi", "en"];
const cycle: Theme[] = ["system", "light", "dark"];

/** Đổi ngôn ngữ ngay trên giao diện và lưu vào hồ sơ (ngôn ngữ là một trường của hồ sơ). */
export function useChangeLocale(): (l: Locale) => void {
  const setLocale = useLocaleStore((s) => s.setLocale);
  const setUser = useAuthStore((s) => s.setUser);
  const save = useMutation({ mutationFn: (locale: Locale) => authApi.updateMe({ locale }), onSuccess: (user) => setUser(user) });
  return (l) => {
    setLocale(l);
    save.mutate(l);
  };
}

export function ThemeToggle() {
  const t = useT();
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const Icon = themeIcon[theme];
  const next = cycle[(cycle.indexOf(theme) + 1) % cycle.length] ?? "system";
  return (
    <Button variant="ghost" size="icon" className="text-muted-foreground" onClick={() => setTheme(next)} aria-label={t(`theme.${theme}`)} data-testid="theme-toggle">
      <Icon className="h-5 w-5" />
    </Button>
  );
}

export function LanguageToggle() {
  const t = useT();
  const locale = useLocaleStore((s) => s.locale);
  const change = useChangeLocale();
  return (
    <div className="inline-flex overflow-hidden rounded-full border border-border" role="group" aria-label={t("action.language")}>
      {LOCALES.map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => change(l)}
          aria-pressed={locale === l}
          data-testid={`lang-${l}`}
          className={cn("px-3 py-1.5 text-xs font-bold transition-colors", locale === l ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
