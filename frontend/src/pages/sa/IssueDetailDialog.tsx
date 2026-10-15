import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { type IssueStatus, obsApi } from "@/features/observability/api";
import { OBS } from "@/features/observability/keys";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Button, CopyableId, Dialog, DialogContent, DialogHeader, DialogTitle, Field, JsonView, NativeSelect, Skeleton } from "@/ui";

import { LogDisabledBanner } from "./LogDisabledBanner";

export const STATUSES = ["open", "resolved", "ignored"] as const satisfies readonly IssueStatus[];

export function IssueDetailDialog({ fingerprint, onClose }: { fingerprint: string; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: OBS.issue(fingerprint), queryFn: () => obsApi.getIssue(fingerprint) });
  const item = data?.item ?? null;
  const [next, setNext] = useState<IssueStatus | null>(null);
  const save = useMutation({
    mutationFn: (s: IssueStatus) => obsApi.setIssueStatus(fingerprint, s),
    onSuccess: (res) => {
      qc.setQueryData(OBS.issue(fingerprint), res);
      void qc.invalidateQueries({ queryKey: OBS.all });
      setNext(null);
      toast.success(t("obs.issue.saved"));
    },
    onError: (err) => toastError(err),
  });
  const meta = (label: string, value: string) => (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-all font-semibold">{value}</dd>
    </div>
  );

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl" data-testid="issue-detail" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle className="break-words pr-10">{item?.title ?? t("obs.issue.loading")}</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : data && !data.enabled ? (
          <LogDisabledBanner />
        ) : item ? (
          <div className="grid min-w-0 gap-4">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm md:grid-cols-3">
              {meta(t("obs.meta.exc"), item.exc_type)}
              {meta(t("obs.meta.loc"), item.loc ?? t("common.none"))}
              {meta(t("obs.meta.source"), item.source)}
              {meta(t("obs.meta.count"), String(item.count))}
              {meta(t("obs.meta.first"), fmt(item.first_seen))}
              {meta(t("obs.meta.last"), fmt(item.last_seen))}
            </dl>
            <div className="flex flex-wrap items-end gap-2">
              <Field id="issue-status" label={t("obs.f.status")}>
                <NativeSelect id="issue-status" className="md:w-48" data-testid="issue-status-select" value={next ?? item.status} onChange={(e) => setNext(e.target.value as IssueStatus)}>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {t(`obs.status.${s}`)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Button data-testid="issue-status-save" disabled={!next || next === item.status || save.isPending} onClick={() => next && save.mutate(next)}>
                {t("common.save")}
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">{t("obs.col.cid")}</span>
              {item.sample.cid ? <CopyableId value={item.sample.cid} short={false} /> : t("common.none")}
              <span className="break-all font-mono text-xs">{item.sample.operation ?? item.sample.path ?? ""}</span>
            </div>
            <section className="grid gap-1.5">
              <h3 className="text-sm font-bold">{t("obs.issue.traceback")}</h3>
              <JsonView value={item.sample.traceback || t("common.none")} maxHeight={320} />
            </section>
            <section className="grid gap-1.5">
              <h3 className="text-sm font-bold">{t("obs.issue.context")}</h3>
              <JsonView value={item.sample.context} maxHeight={240} />
            </section>
            <section className="grid gap-1.5">
              <h3 className="text-sm font-bold">{t("obs.issue.recent")}</h3>
              <ul className="space-y-1 text-xs">
                {(item.recent ?? []).map((r, i) => (
                  <li key={`${r.cid ?? "x"}-${i}`} className="flex flex-wrap items-center gap-2">
                    <span className="num text-muted-foreground">{fmt(r.ts)}</span>
                    {r.cid ? <CopyableId value={r.cid} /> : null}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
