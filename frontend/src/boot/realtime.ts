/** App xử lý sẵn event lõi; trang chỉ nghe event của miền nó qua useRealtime. */
import { useEffect } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { authApi } from "@/features/auth/api";
import { AUTH } from "@/features/auth/keys";
import { NOTIF } from "@/features/notifications/keys";
import { notifTitle } from "@/features/notifications/notif";
import { useAuthStore } from "@/lib/auth/store";
import { translate } from "@/lib/i18n";
import { queryClient } from "@/lib/query-client";
import { type RealtimeHandler, socketManager } from "@/lib/realtime/socket";

export async function reloadMe(): Promise<void> {
  const me = await authApi.me();
  useAuthStore.getState().setUser(me);
  queryClient.setQueryData(AUTH.me(), me);
}

const invalidate = (queryKey: readonly unknown[]) => void queryClient.invalidateQueries({ queryKey });
const quiet = (p: Promise<unknown>) => void p.catch(() => undefined);

type NotificationPush = { kind?: string; title?: string; body?: string | null; params?: Record<string, unknown> | null };

export function useCoreRealtime(): void {
  const authed = useAuthStore((s) => s.isAuthenticated);
  const navigate = useNavigate();

  useEffect(() => {
    if (authed) socketManager.connect();
  }, [authed]);

  useEffect(() => {
    const handlers: Record<string, RealtimeHandler> = {
      "auth:expired": () => quiet(socketManager.refreshAuth()),
      "core:rbac_updated": () =>
        quiet(
          (async () => {
            await socketManager.refreshAuth();
            await reloadMe(); // store đổi → guard quyền tự chuyển /403 nếu trang hiện tại không còn được xem
            toast.info(translate("rt.rbacUpdated"));
          })(),
        ),
      "data:changed": (data) => {
        for (const k of (data as { keys?: string[] } | null)?.keys ?? []) invalidate(k.split("."));
      },
      "core:notification": (data) => {
        const n = data as NotificationPush | null;
        invalidate(NOTIF.all);
        if (n?.title) toast(notifTitle(translate, { kind: n.kind ?? "", title: n.title, params: n.params }), { description: n.body || undefined });
      },
      "core:account_disabled": () => {
        toast.error(translate("rt.accountDisabled"));
        useAuthStore.getState().logout();
        void navigate("/login?reason=disabled", { replace: true });
      },
      "sys:error": (data, meta) => {
        const d = data as { code?: number; cid?: string } | null;
        const cid = d?.cid ?? meta?.cid;
        toast.error(translate("rt.sysError", { code: d?.code ?? "?" }), {
          description: cid ? translate("error.lookup", { cid }) : undefined,
        });
      },
    };
    const offs = Object.entries(handlers).map(([event, handler]) => socketManager.on(event, handler));
    return () => {
      for (const off of offs) off();
    };
  }, [navigate]);
}
