import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff, Check, CheckCheck, ExternalLink } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { markReadFast, type Notification, notificationsApi } from "@/features/notifications/api";
import { NOTIF } from "@/features/notifications/keys";
import { notifLink, notifOperation, notifTitle, notifUrl, runNotifOperation } from "@/features/notifications/notif";
import { cn } from "@/lib/cn";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { useIsDesktop } from "@/lib/use-media";
import { Button, Cell, EmptyState, Row, ServerPagination, Skeleton, Switch, Table, TruncText } from "@/ui";

import { PushCard } from "./PushCard";

const LIMIT = 20;

export default function NotificationsPage() {
  const t = useT();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const desktop = useIsDesktop();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const q = { unread_only: unreadOnly, limit: LIMIT, offset };
  const { data, isLoading } = useQuery({ queryKey: NOTIF.list(q), queryFn: () => notificationsApi.list(q), placeholderData: keepPreviousData });
  const markAll = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => qc.invalidateQueries({ queryKey: NOTIF.all }),
    onError: (err) => toastError(err),
  });
  const items = data?.items ?? [];
  const read = (n: Notification) => void markReadFast(qc, [n.id]);
  const open = (n: Notification, to: string) => {
    if (!n.read_at) read(n);
    void navigate(to);
  };

  const runOp = useMutation({
    mutationFn: (n: Notification) => runNotifOperation(notifOperation(n) as NonNullable<ReturnType<typeof notifOperation>>),
    onSuccess: (_, n) => {
      if (!n.read_at) read(n);
      toast.success(t("notif.opDone"));
      void qc.invalidateQueries();
    },
    onError: (err) => toastError(err),
  });

  const actions = (n: Notification) => {
    const to = notifLink(n);
    const op = notifOperation(n);
    const ext = notifUrl(n);
    return (
      <div className="flex shrink-0 gap-1">
        {ext ? (
          <Button asChild size="sm" variant="outline" data-testid={`notif-url-${n.id}`}>
            <a href={ext.url} target="_blank" rel="noopener noreferrer" onClick={() => !n.read_at && read(n)}>
              <ExternalLink className="h-4 w-4" />
              {ext.label || t("notif.open")}
            </a>
          </Button>
        ) : null}
        {op ? (
          <Button size="sm" data-testid={`notif-op-${n.id}`} disabled={runOp.isPending} onClick={() => runOp.mutate(n)}>
            {op.label}
          </Button>
        ) : null}
        {to ? (
          <Button size="icon" variant="ghost" aria-label={t("notif.open")} data-testid={`notif-open-${n.id}`} onClick={() => open(n, to)}>
            <ExternalLink className="h-4 w-4" />
          </Button>
        ) : null}
        {!n.read_at ? (
          <Button size="icon" variant="ghost" aria-label={t("notif.markRead")} data-testid={`notif-read-${n.id}`} onClick={() => read(n)}>
            <Check className="h-4 w-4" />
          </Button>
        ) : null}
      </div>
    );
  };
  const dot = (n: Notification) => <span aria-hidden className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", n.read_at ? "bg-border" : "bg-brand")} />;

  return (
    <div className="space-y-4">
      <PushCard />
      <div className="flex flex-wrap items-center justify-end gap-3">
        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm md:min-h-9">
          <Switch checked={unreadOnly} data-testid="notif-unread-only" onCheckedChange={(v) => { setOffset(0); setUnreadOnly(v); }} />
          {t("notif.unreadOnly")}
        </label>
        <Button variant="outline" onClick={() => markAll.mutate()} disabled={markAll.isPending} data-testid="notif-mark-all">
          <CheckCheck className="h-4 w-4" />
          {t("notif.markAllRead")}
        </Button>
      </div>
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon={<BellOff className="h-10 w-10" />} title={t("notif.empty")} />
      ) : desktop ? (
        <Table head={["", t("notif.col.title"), t("notif.col.body"), t("notif.col.time"), ""]}>
          {items.map((n) => (
            <Row key={n.id} testId={`notif-item-${n.id}`} className={cn(!n.read_at && "bg-brand-muted/40")}>
              <Cell className="w-6">{dot(n)}</Cell>
              <Cell className="max-w-[320px] font-semibold">
                <TruncText text={notifTitle(t, n)} />
              </Cell>
              <Cell className="max-w-[420px] text-muted-foreground">
                <TruncText text={n.body || t("common.none")} />
              </Cell>
              <Cell className="num whitespace-nowrap text-muted-foreground">{fmt(n.created_at, "relative")}</Cell>
              <Cell className="w-24">{actions(n)}</Cell>
            </Row>
          ))}
        </Table>
      ) : (
        <ul className="space-y-2">
          {items.map((n) => (
            <li
              key={n.id}
              data-testid={`notif-item-${n.id}`}
              className={cn("flex min-w-0 items-start gap-3 rounded-2xl border border-border bg-card p-4 shadow-card", !n.read_at && "bg-brand-muted/40")}
            >
              {dot(n)}
              <div className="min-w-0 flex-1">
                <div className="break-words text-sm font-semibold">{notifTitle(t, n)}</div>
                {n.body ? <div className="break-words text-sm text-muted-foreground">{n.body}</div> : null}
                <div className="num mt-1 text-xs text-muted-foreground">{fmt(n.created_at, "relative")}</div>
              </div>
              {actions(n)}
            </li>
          ))}
        </ul>
      )}
      <ServerPagination offset={offset} limit={LIMIT} total={data?.total ?? 0} onChange={setOffset} />
    </div>
  );
}
