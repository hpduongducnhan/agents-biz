import { useQuery } from "@tanstack/react-query";
import { Bell, ChevronRight, Sparkles } from "lucide-react";
import { type ReactNode, Suspense } from "react";
import { Link } from "react-router";

import { notificationsApi } from "@/features/notifications/api";
import { NOTIF } from "@/features/notifications/keys";
import { InstallHint } from "@/layout/InstallGuide";
import { useCanUseAssistant, useCurrentUser } from "@/lib/auth/permissions";
import { useT } from "@/lib/i18n";
import { moduleWidgets } from "@/modules/access";
import { Card, Skeleton } from "@/ui";

function Shortcut({ to, icon, title, desc, testId }: { to: string; icon: ReactNode; title: string; desc: string; testId: string }) {
  return (
    <Link
      to={to}
      data-testid={testId}
      className="flex min-h-[44px] items-center gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:bg-accent"
    >
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-muted text-brand">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block font-bold">{title}</span>
        <span className="block truncate text-sm text-muted-foreground">{desc}</span>
      </span>
      <ChevronRight className="h-4 w-4 text-muted-foreground" />
    </Link>
  );
}

/** Tổng quan: lời chào, gợi ý cài app, widget của module (registry — D25), lối tắt Trợ lý + Thông báo. */
export default function OverviewPage() {
  const t = useT();
  const me = useCurrentUser();
  const canChat = useCanUseAssistant();
  const { data: unread } = useQuery({ queryKey: NOTIF.unread(), queryFn: () => notificationsApi.unreadCount() });

  return (
    <div className="space-y-5">
      <InstallHint />
      <Card className="space-y-1 p-4" data-testid="overview-hello">
        <h2 className="text-lg font-extrabold">{t("overview.hello", { name: me?.name || me?.email || "" })}</h2>
        <p className="text-sm text-muted-foreground">{t("overview.intro")}</p>
      </Card>
      {moduleWidgets(me).map((w) => (
        <Suspense key={w.id} fallback={<Skeleton className="h-32 w-full" />}>
          <w.component />
        </Suspense>
      ))}
      <div className="grid gap-3 sm:grid-cols-2">
        {canChat && (
          <Shortcut to="/assistant" testId="overview-assistant" icon={<Sparkles className="h-5 w-5" />} title={t("nav.assistant")} desc={t("overview.ask")} />
        )}
        <Shortcut
          to="/notifications"
          testId="overview-notifications"
          icon={<Bell className="h-5 w-5" />}
          title={t("nav.notifications")}
          desc={t("overview.unread", { n: unread?.count ?? 0 })}
        />
      </div>
    </div>
  );
}
