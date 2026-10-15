import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";

import { authApi } from "@/features/auth/api";
import { usePublicInfo } from "@/features/system/hooks";
import { setTokens } from "@/lib/auth-tokens";
import { useAuthStore } from "@/lib/auth/store";
import { useT } from "@/lib/i18n";

/** Google redirect về kèm token ở FRAGMENT (không vào log server / Referer) — đọc rồi xoá khỏi URL ngay. */
export default function AuthCallbackPage() {
  const t = useT();
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const { data: info, isError } = usePublicInfo();
  const started = useRef(false); // StrictMode chạy effect hai lần: lần hai không còn fragment

  useEffect(() => {
    if (started.current || (!info && !isError)) return;
    started.current = true;
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    window.history.replaceState(null, "", window.location.pathname);
    if (!info?.google_enabled) {
      void navigate("/login?error=2108", { replace: true });
      return;
    }
    const access = params.get("access_token");
    const refresh = params.get("refresh_token");
    if (!access || !refresh) {
      void navigate(`/login?error=${encodeURIComponent(params.get("error") ?? "google")}`, { replace: true });
      return;
    }
    setTokens(access, refresh);
    authApi.me().then(
      (user) => {
        login({ access_token: access, refresh_token: refresh }, user);
        void navigate("/", { replace: true });
      },
      () => void navigate("/login?error=google", { replace: true }),
    );
  }, [info, isError, login, navigate]);

  return <div className="flex h-dvh items-center justify-center p-4 text-muted-foreground">{t("auth.callback.loading")}</div>;
}
