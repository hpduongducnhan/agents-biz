import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ScrollText } from "lucide-react";
import { Fragment, useState } from "react";

import { type EventEntry, obsApi } from "@/features/observability/api";
import { OBS } from "@/features/observability/keys";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { useDebounced } from "@/lib/use-debounced";
import { useIsDesktop } from "@/lib/use-media";
import { Badge, Button, CopyableId, EmptyState, JsonView, Row, ServerPagination, Skeleton, Table, TruncText, Cell } from "@/ui";

import { EMPTY_FILTERS, EventFilters, type EventFilterState, toEventQuery } from "./EventFilters";
import { LogDisabledBanner } from "./LogDisabledBanner";

export default function EventsPage() {
  const t = useT();
  const desktop = useIsDesktop();
  const [filters, setFilters] = useState<EventFilterState>(EMPTY_FILTERS);
  const debounced = useDebounced(filters);
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const q = toEventQuery(debounced, offset);
  const { data, isLoading } = useQuery({ queryKey: OBS.events(q), queryFn: () => obsApi.listEvents(q), placeholderData: keepPreviousData });
  const items = data?.items ?? [];

  const result = (e: EventEntry) =>
    e.ok ? <Badge variant="secondary">{t("obs.ok")}</Badge> : <Badge variant="destructive">{`${t("obs.fail")}${e.error_code ? ` ${e.error_code}` : ""}`}</Badge>;
  const actor = (e: EventEntry) => (
    <span className="flex min-w-0 items-center gap-1">
      {e.actor_id ? <CopyableId value={e.actor_id} /> : <span className="text-muted-foreground">{t("obs.system")}</span>}
      {e.is_superadmin ? <Badge variant="outline">SA</Badge> : null}
    </span>
  );
  const toggle = (e: EventEntry) => (
    <Button size="icon" variant="ghost" aria-expanded={open === e.id} aria-label={open === e.id ? t("obs.hideInput") : t("obs.showInput")} data-testid={`event-toggle-${e.id}`} onClick={() => setOpen(open === e.id ? null : e.id)}>
      <ChevronDown className={open === e.id ? "h-4 w-4 rotate-180 transition-transform" : "h-4 w-4 transition-transform"} />
    </Button>
  );

  return (
    <div className="space-y-4">
      <EventFilters
        value={filters}
        onChange={(f) => {
          setOffset(0);
          setFilters(f);
        }}
      />
      {data && !data.enabled ? (
        <LogDisabledBanner />
      ) : isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : items.length === 0 ? (
        <EmptyState icon={<ScrollText className="h-10 w-10" />} title={t("obs.empty.events")} />
      ) : desktop ? (
        <Table head={[t("obs.col.time"), t("obs.col.operation"), t("obs.col.actor"), t("obs.col.source"), t("obs.col.result"), "ms", t("obs.col.cid"), ""]}>
          {items.map((e) => (
            <Fragment key={e.id}>
              <Row testId={`event-item-${e.id}`}>
                <Cell className="num whitespace-nowrap">{fmt(e.ts, "datetime")}</Cell>
                <Cell className="max-w-[240px]">
                  <TruncText text={e.operation} mono />
                </Cell>
                <Cell className="max-w-[180px]">{actor(e)}</Cell>
                <Cell>
                  <Badge variant="outline">{e.source}</Badge>
                </Cell>
                <Cell>{result(e)}</Cell>
                <Cell className="num text-right">{e.duration_ms}</Cell>
                <Cell>{e.cid ? <CopyableId value={e.cid} /> : t("common.none")}</Cell>
                <Cell className="w-12">{toggle(e)}</Cell>
              </Row>
              {open === e.id && (
                <tr data-testid={`event-json-${e.id}`}>
                  <td colSpan={8} className="px-4 pb-4">
                    <JsonView value={e.input ?? {}} maxHeight={320} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </Table>
      ) : (
        <ul className="space-y-2">
          {items.map((e) => (
            <li key={e.id} data-testid={`event-item-${e.id}`} className="min-w-0 space-y-2 rounded-2xl border border-border bg-card p-4 shadow-card">
              <div className="flex items-center justify-between gap-2">
                <span className="num text-xs text-muted-foreground">{fmt(e.ts, "datetime")}</span>
                {result(e)}
              </div>
              <div className="break-all font-mono text-sm">{e.operation}</div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                {actor(e)}
                <Badge variant="outline">{e.source}</Badge>
                <span className="num text-muted-foreground">{e.duration_ms} ms</span>
                {toggle(e)}
              </div>
              {open === e.id && (
                <div data-testid={`event-json-${e.id}`}>
                  <JsonView value={e.input ?? {}} maxHeight={280} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {data?.enabled !== false && <ServerPagination offset={offset} limit={20} total={data?.total ?? 0} onChange={setOffset} />}
    </div>
  );
}
