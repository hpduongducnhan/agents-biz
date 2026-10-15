import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useNavigate } from "react-router";

import { markReadFast, notificationsApi } from "@/features/notifications/api";
import { NOTIF } from "@/features/notifications/keys";
import { notifLink, notifTitle, notifUrl } from "@/features/notifications/notif";
import { useAuthStore } from "@/lib/auth/store";
import { cn } from "@/lib/cn";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, ScrollArea } from "@/ui";

const RECENT = { limit: 10, offset: 0 };

export function NotificationBell() {
  const t = useT();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const authed = useAuthStore((s) => s.isAuthenticated);
  const { data: unread } = useQuery({ queryKey: NOTIF.unread(), queryFn: () => notificationsApi.unreadCount(), enabled: authed });
  const { data: recent } = useQuery({ queryKey: NOTIF.list(RECENT), queryFn: () => notificationsApi.list(RECENT), enabled: authed });
  const markAll = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => qc.invalidateQueries({ queryKey: NOTIF.all }),
  });
  const count = unread?.count ?? 0;
  const items = recent?.items ?? [];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={t("notif.title")} data-testid="notification-bell">
          <Bell className="h-5 w-5" />
          {count > 0 && (
            <span
              data-testid="notification-count"
              className="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-bold tabular-nums text-destructive-foreground"
            >
              {count > 9 ? "9+" : count}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[min(20rem,calc(100vw-1.5rem))]">
        <div className="flex items-center justify-between gap-2 px-2 py-1.5">
          <span className="text-sm font-bold">{t("notif.title")}</span>
          {count > 0 && (
            <Button variant="link" size="sm" className="h-9 px-1" onClick={() => markAll.mutate()}>
              {t("notif.markAllRead")}
            </Button>
          )}
        </div>
        <DropdownMenuSeparator />
        {items.length === 0 && <div className="px-2 py-6 text-center text-sm text-muted-foreground">{t("notif.empty")}</div>}
        <ScrollArea className="max-h-80">
          {items.map((n) => (
            <DropdownMenuItem
              key={n.id}
              className={cn("flex flex-col items-start gap-0.5 whitespace-normal py-2", !n.read_at && "bg-brand-muted/60")}
              onSelect={() => {
                if (!n.read_at) void markReadFast(qc, [n.id]);
                const to = notifLink(n);
                const ext = notifUrl(n);
                if (to) void navigate(to);
                else if (ext) window.open(ext.url, "_blank", "noopener,noreferrer");
              }}
            >
              <span className="w-full break-words text-sm font-semibold">{notifTitle(t, n)}</span>
              {n.body ? <span className="w-full break-words text-xs text-muted-foreground">{n.body}</span> : null}
              <span className="text-[11px] text-muted-foreground">{fmt(n.created_at, "relative")}</span>
            </DropdownMenuItem>
          ))}
        </ScrollArea>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="justify-center text-sm font-semibold text-brand" onSelect={() => void navigate("/notifications")}>
          {t("notif.viewAll")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
