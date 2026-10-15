import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { traceApi } from "@/features/agent/api";
import { TRACES } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { EmptyState, ServerPagination, Skeleton } from "@/ui";

import { LogDisabledBanner } from "./LogDisabledBanner";
import { useTraceFilters } from "./traces/filters";
import { TraceFilters } from "./traces/TraceFilters";
import { TraceItem } from "./traces/TraceItem";

const LIMIT = 20;

/** Trace agent (superadmin): lượt gần đây (span `run`) — lọc user / phiên / agent / trạng thái / model / ngày / có lỗi
 *  (bộ lọc trên URL); Mongo tắt → banner như trang log. */
export default function TracesPage() {
  const t = useT();
  const { query } = useTraceFilters();
  const [offset, setOffset] = useState(0);
  const key = JSON.stringify(query);
  useEffect(() => setOffset(0), [key]);
  const q = { ...query, limit: LIMIT, offset };
  const { data, isLoading } = useQuery({ queryKey: TRACES.list(q), queryFn: () => traceApi.list(q), placeholderData: keepPreviousData });
  if (data && !data.enabled) return <LogDisabledBanner />;
  const items = data?.items ?? [];
  return (
    <div className="grid min-w-0 gap-3">
      <TraceFilters />
      <span className="text-xs text-muted-foreground" data-testid="trace-count">
        {t("trace.count", { n: data?.total ?? 0 })}
      </span>
      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : !items.length ? (
        <EmptyState title={t("trace.empty")} />
      ) : (
        <ul className="grid gap-2" data-testid="trace-list">
          {items.map((r) => (
            <TraceItem key={r.id} run={r} names={data?.names ?? {}} />
          ))}
        </ul>
      )}
      <ServerPagination offset={offset} limit={LIMIT} total={data?.total ?? 0} onChange={setOffset} />
    </div>
  );
}
