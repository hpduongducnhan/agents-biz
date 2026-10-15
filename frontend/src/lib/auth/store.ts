import { create } from "zustand";

import { clearTokens, setTokens } from "@/lib/auth-tokens";
import { type Locale, useLocaleStore } from "@/lib/i18n";
import { queryClient } from "@/lib/query-client";
import { socketManager } from "@/lib/realtime/socket";

import type { Me, SessionTokens } from "./types";

type AuthState = {
  isAuthenticated: boolean;
  user: Me | null;
  login: (tokens: SessionTokens, user: Me) => void;
  logout: () => void;
  setUser: (user: Me) => void;
};

/** Ngôn ngữ đã lưu trong hồ sơ thắng lựa chọn cục bộ của trình duyệt. */
function applyUserLocale(user: Me): void {
  const want: Locale = String(user.locale) === "en" ? "en" : "vi";
  const { locale, setLocale } = useLocaleStore.getState();
  if (locale !== want) setLocale(want);
}

// Cache thuộc một danh tính — login: `resetQueries` (tải lại bằng token mới, observer đang mount vẫn gắn cache);
// logout: `clear()`. Socket bắt tay bằng token cũ → ngắt rồi nối lại ngay.
export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  user: null,
  login: (tokens, user) => {
    setTokens(tokens.access_token, tokens.refresh_token);
    socketManager.disconnect();
    socketManager.connect();
    applyUserLocale(user);
    set({ isAuthenticated: true, user });
    void queryClient.resetQueries();
  },
  logout: () => {
    queryClient.clear();
    clearTokens();
    socketManager.disconnect();
    set({ isAuthenticated: false, user: null });
  },
  setUser: (user) => {
    applyUserLocale(user);
    set({ user, isAuthenticated: true });
  },
}));
