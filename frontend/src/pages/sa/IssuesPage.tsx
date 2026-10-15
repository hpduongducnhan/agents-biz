import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Bug, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { type Issue, type IssueStatus, obsApi } from "@/features/observability/api";
import { OBS } from "@/features/observability/keys";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { useIsDesktop } from "@/lib/use-media";
import { Badge, Button, Cell, EmptyState, NativeSelect, Row, ServerPagination, Skeleton, Table, TruncText } from "@/ui";

import { IssueDetailDialog, STATUSES } from "./IssueDetailDialog";
import { LogDisabledBanner } from "./LogDisabledBanner";

const LIMIT = 20;

export default function IssuesPage() {
  const t = useT();
  const desktop = useIsDesktop();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<IssueStatus | "">("open");
  const [offset, setOffset] = useState(0);
  const q = { limit: LIMIT, offset, ...(status ? { status } : {}) };
  const { data, isLoading } = useQuery({ queryKey: OBS.issues(q), queryFn: () => obsApi.listIssues(q), placeholderData: keepPreviousData });
  const items = data?.items ?? [];
  const fp = params.get("fp");
  const openIssue = (i: Issue) => setParams({ fp: i.fingerprint });
  const statusBadge = (i: Issue) => (
    <Badge variant={i.status === "open" ? "destructive" : "secondary"}>{t(`obs.status.${i.status}`)}</Badge>
  );
  const openBtn = (i: Issue) => (
    <Button size="icon" variant="ghost" aria-label={t("obs.issue.open")} data-testid={`issue-open-${i.fingerprint}`} onClick={() => openIssue(i)}>
      <ChevronRight className="h-4 w-4" />
    </Button>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <NativeSelect
          className="md:h-9 md:w-48"
          aria-label={t("obs.f.status")}
          data-testid="issues-filter-status"
          value={status}
          onChange={(e) => {
            setOffset(0);
            setStatus(STATUSES.find((s) => s === e.target.value) ?? "");
          }}
        >
          <option value="">{t("obs.f.allStatus")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`obs.status.${s}`)}
            </option>
          ))}
        </NativeSelect>
      </div>
      {data && !data.enabled ? (
        <LogDisabledBanner />
      ) : isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : items.length === 0 ? (
        <EmptyState icon={<Bug className="h-10 w-10" />} title={t("obs.empty.issues")} />
      ) : desktop ? (
        <Table head={[t("obs.col.issue"), t("obs.meta.loc"), t("obs.meta.count"), t("obs.meta.last"), t("obs.f.status"), ""]}>
          {items.map((i) => (
            <Row key={i.fingerprint} testId={`issue-item-${i.fingerprint}`} onClick={() => openIssue(i)}>
              <Cell className="max-w-[380px] font-semibold">
                <TruncText text={i.title} />
              </Cell>
              <Cell className="max-w-[180px]">
                <TruncText text={i.loc ?? t("common.none")} mono />
              </Cell>
              <Cell className="num">{i.count}</Cell>
              <Cell className="num whitespace-nowrap text-muted-foreground">{fmt(i.last_seen, "relative")}</Cell>
              <Cell>{statusBadge(i)}</Cell>
              <Cell className="w-12">{openBtn(i)}</Cell>
            </Row>
          ))}
        </Table>
      ) : (
        <ul className="space-y-2">
          {items.map((i) => (
            <li key={i.fingerprint} data-testid={`issue-item-${i.fingerprint}`} className="flex min-w-0 items-start gap-3 rounded-2xl border border-border bg-card p-4 shadow-card">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="break-words font-semibold">{i.title}</div>
                <div className="break-all font-mono text-xs text-muted-foreground">{i.loc ?? i.exc_type}</div>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  {statusBadge(i)}
                  <span className="num">{t("obs.issue.times", { n: i.count })}</span>
                  <span className="num text-muted-foreground">{fmt(i.last_seen, "relative")}</span>
                </div>
              </div>
              {openBtn(i)}
            </li>
          ))}
        </ul>
      )}
      {data?.enabled !== false && <ServerPagination offset={offset} limit={LIMIT} total={data?.total ?? 0} onChange={setOffset} />}
      {fp && <IssueDetailDialog fingerprint={fp} onClose={() => setParams({}, { replace: true })} />}
    </div>
  );
}
