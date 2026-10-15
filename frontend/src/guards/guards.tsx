/** Guard ở route: đăng nhập → quyền / superadmin. Ẩn UI chỉ là UX; chặn thật ở đây + BE. */
import { useQuery } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";
import { type ReactNode, useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { authApi } from "@/features/auth/api";
import { AUTH } from "@/features/auth/keys";
import { ApiError } from "@/lib/api/errors";
import { getAccessToken, getRefreshToken } from "@/lib/auth-tokens";
import { hasPermission, type Perm } from "@/lib/auth/permissions";
import { useAuthStore } from "@/lib/auth/store";
import { useT } from "@/lib/i18n";
import { Button, Skeleton } from "@/ui";

function FullscreenSkeleton() {
  return (
    <div className="flex h-dvh items-center justify-center bg-background">
      <div className="w-64 space-y-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    </div>
  );
}

/** Mất mạng / server lỗi lúc mở app (PWA offline): giữ phiên, cho thử lại; tự thử khi có mạng lại. */
function OfflineScreen({ onRetry }: { onRetry: () => void }) {
  const t = useT();
  useEffect(() => {
    window.addEventListener("online", onRetry);
    return () => window.removeEventListener("online", onRetry);
  }, [onRetry]);
  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-4 bg-background p-6 text-center" data-testid="offline-screen">
      <WifiOff className="h-10 w-10 text-muted-foreground" aria-hidden />
      <p className="text-lg font-extrabold">{t("offline.title")}</p>
      <p className="max-w-xs text-sm text-muted-foreground">{t("offline.desc")}</p>
      <Button onClick={onRetry} data-testid="offline-retry">
        {t("offline.retry")}
      </Button>
    </div>
  );
}

const rejectedSession = (err: unknown) => err instanceof ApiError && err.status >= 400 && err.status < 500;

export function ProtectedRoute() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const logout = useAuthStore((s) => s.logout);
  const location = useLocation();
  // Access token chỉ ở bộ nhớ: mở lại trang chỉ còn refresh token — interceptor làm mới trước khi gửi /auth/me.
  const hasSession = !!getAccessToken() || !!getRefreshToken();
  const { data, error, refetch } = useQuery({
    queryKey: AUTH.me(),
    queryFn: () => authApi.me(),
    enabled: hasSession,
    retry: false,
    staleTime: 5 * 60_000,
    meta: { silent: true },
  });

  useEffect(() => {
    if (data) setUser(data);
  }, [data, setUser]);
  const rejected = rejectedSession(error);
  useEffect(() => {
    if (rejected) logout();
  }, [rejected, logout]);

  const next = encodeURIComponent(location.pathname + location.search);
  if (!hasSession || rejected) return <Navigate to={`/login?next=${next}`} replace />;
  if (error && !user) return <OfflineScreen onRetry={() => void refetch()} />;
  // Chờ user vào store rồi mới render con — không thì guard quyền đọc user=null và đá về /403.
  if (!user) return <FullscreenSkeleton />;
  if (user.must_change_password && location.pathname !== "/profile") return <Navigate to="/profile?tab=password" replace />;
  return <Outlet />;
}

export function RequirePermission({ permission, children }: { permission: Perm; children?: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!hasPermission(user, permission)) return <Navigate to="/403" replace />;
  return children ?? <Outlet />;
}

export function RequireSuperadmin() {
  const sup = useAuthStore((s) => !!s.user?.is_superadmin);
  return sup ? <Outlet /> : <Navigate to="/403" replace />;
}
