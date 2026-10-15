import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { traceApi } from "@/features/agent/api";
import { USAGE } from "@/features/agent/keys";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { Badge, Card, EmptyState, NativeSelect, ServerPagination, Skeleton } from "@/ui";

import { useUsageFilters } from "./filters";

const LIMIT = 10;
const KINDS = ["rate", "auth", "server", "other"] as const;

/** Lần gọi LLM lỗi gần nhất (cùng bộ lọc trang): loại, model, agent, user, key, nội dung (đã che), link sang trace. */
export function LlmErrors() {
  const t = useT();
  const { query } = useUsageFilters();
  const [kind, setKind] = useState<(typeof KINDS)[number] | "">("");
  const [offset, setOffset] = useState(0);
  const q = { ...query, ...(kind ? { kind } : {}), limit: LIMIT, offset };
  const { data, isLoading } = useQuery({ queryKey: USAGE.errors(q), queryFn: () => traceApi.usageErrors(q), placeholderData: keepPreviousData });
  const items = data?.items ?? [];
  return (
    <Card className="grid min-w-0 gap-3 p-3" data-testid="llm-errors">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-bold">{t("usage.errors.title")}</h2>
        <NativeSelect
          aria-label={t("usage.errors.kindAll")}
          className="w-52"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value as typeof kind);
            setOffset(0);
          }}
          data-testid="llm-errors-kind"
        >
          <option value="">{t("usage.errors.kindAll")}</option>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`usage.errors.kind.${k}`)}
            </option>
          ))}
        </NativeSelect>
      </div>
      {isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : !items.length ? (
        <EmptyState title={t("usage.errors.empty")} />
      ) : (
        <ul className="grid gap-2">
          {items.map((e) => (
            <li key={e.id} className="grid min-w-0 gap-1 rounded-2xl border border-border bg-card p-3 text-sm" data-testid={`llm-error-${e.id}`}>
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Badge variant="destructive">{t(`usage.errors.kind.${e.kind ?? "other"}`)}</Badge>
                <span className="text-xs text-muted-foreground">{fmt(e.at)}</span>
                <span className="min-w-0 truncate text-xs font-semibold">
                  {[e.model, e.agent, e.purpose ? t(`usage.purpose.${e.purpose}`) : null].filter(Boolean).join(" · ")}
                </span>
                {e.run_id ? (
                  <Link to={`/sa/traces/${e.run_id}`} className="ml-auto text-xs font-semibold text-primary underline-offset-2 hover:underline">
                    {t("usage.toTraces")}
                  </Link>
                ) : null}
              </div>
              <span className="truncate text-xs text-muted-foreground">{[e.user, e.key, e.latency_ms != null ? `${e.latency_ms} ms` : null].filter(Boolean).join(" · ")}</span>
              {e.error ? <p className="line-clamp-3 break-words font-mono text-xs">{e.error}</p> : null}
            </li>
          ))}
        </ul>
      )}
      <ServerPagination offset={offset} limit={LIMIT} total={data?.total ?? 0} onChange={setOffset} />
    </Card>
  );
}
