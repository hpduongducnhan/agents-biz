import { create } from "zustand";
import { persist } from "zustand/middleware";

// Nguồn sự thật = `documentElement.lang` — transport đọc đúng chỗ này để gắn Accept-Language.
export type Locale = "vi" | "en";

function applyLocale(locale: Locale): void {
  document.documentElement.lang = locale;
}

type LocaleState = {
  locale: Locale;
  /** Tăng mỗi lần nạp thêm dictionary (module lazy) → `useT` re-render. */
  version: number;
  setLocale: (l: Locale) => void;
  bump: () => void;
};

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      locale: "vi",
      version: 0,
      setLocale: (l) => {
        applyLocale(l);
        set({ locale: l });
      },
      bump: () => set((s) => ({ version: s.version + 1 })),
    }),
    {
      name: "bw-locale-v1",
      partialize: (s) => ({ locale: s.locale }),
      onRehydrateStorage: () => (state) => {
        if (state) applyLocale(state.locale);
      },
    },
  ),
);
