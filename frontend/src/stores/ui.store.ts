import { create } from "zustand";
import { persist } from "zustand/middleware";

// Theme: nguồn sự thật = `data-theme` trên <html>; "system" = bỏ attribute để theo prefers-color-scheme.
export type Theme = "light" | "dark" | "system";

function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

type UiState = {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  /** Nhóm con của sidebar người dùng đã mở / gập tay; chưa chạm → mở khi chứa trang hiện tại. */
  navGroups: Record<string, boolean>;
  setNavGroup: (key: string, open: boolean) => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
  /** Hướng dẫn thêm vào màn hình chính: mở từ banner Tổng quan, menu trái, menu người dùng. */
  installGuideOpen: boolean;
  setInstallGuide: (open: boolean) => void;
  installHintDismissed: boolean;
  dismissInstallHint: () => void;
};

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      navGroups: {},
      setNavGroup: (key, open) => set((s) => ({ navGroups: { ...s.navGroups, [key]: open } })),
      theme: "system",
      setTheme: (t) => {
        applyTheme(t);
        set({ theme: t });
      },
      installGuideOpen: false,
      setInstallGuide: (open) => set({ installGuideOpen: open }),
      installHintDismissed: false,
      dismissInstallHint: () => set({ installHintDismissed: true }),
    }),
    {
      name: "bw-ui-v1",
      partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed, theme: s.theme, navGroups: s.navGroups, installHintDismissed: s.installHintDismissed }),
      onRehydrateStorage: () => (state) => {
        if (state) applyTheme(state.theme);
      },
    },
  ),
);

/** Tiêu đề + mô tả trang hiện ở Header (FE rule 18) — route đặt qua <Titled>. */
export const usePageMeta = create<{ title: string; subtitle?: string; set: (t: string, s?: string) => void }>((set) => ({
  title: "",
  subtitle: undefined,
  set: (title, subtitle) => set({ title, subtitle }),
}));
