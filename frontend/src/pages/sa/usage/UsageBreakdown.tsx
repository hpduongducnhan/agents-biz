import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { type UsageRow, traceApi } from "@/features/agent/api";
import { USAGE } from "@/features/agent/keys";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { useIsDesktop } from "@/lib/use-media";
import { Card, Cell, EmptyState, Row, Skeleton, Table, TruncText } from "@/ui";

import { compact, FILTER_OF, type Group, GROUPS, pct, usd, useUsageFilters } from "./filters";

function useName() {
  const t = useT();
  return (by: Group, r: UsageRow) => {
    if (by === "purpose") return t(`usage.purpose.${r.key}`);
    if (by === "key" && r.key === "none") return t("usage.noKey");
    if (by === "tenant" && r.key === "none") return t("usage.noTenant");
    return r.name || r.sub || r.key.slice(0, 8);
  };
}

const price = (r: UsageRow) => (r.prices ? `$${Number(r.prices.input)} · $${Number(r.prices.output)} · $${Number(r.prices.cache_read)}` : "—");
const tokens = (r: UsageRow) => `${compact(r.input_tokens + r.cache_read_tokens + r.cache_write_tokens)} / ${compact(r.output_tokens)}`;
const cache = (r: UsageRow) => `${compact(r.cache_read_tokens)} / ${compact(r.cache_write_tokens)} (${pct(r.cache_read_tokens, r.input_tokens + r.cache_read_tokens + r.cache_write_tokens)}%)`;
const errors = (r: UsageRow) => (r.errors ? `${r.errors} (${pct(r.errors, r.requests)}%)` : "0");
const latency = (r: UsageRow) => (r.latency_avg_ms != null ? `${compact(r.latency_avg_ms)} ms` : "—");

/** Phân tích theo một chiều (tab): provider / model / agent / nơi gọi / user / key. Bấm dòng → thêm bộ lọc chiều đó. */
export function UsageBreakdown() {
  const t = useT();
  const desktop = useIsDesktop();
  const name = useName();
  const { by, query, set, filters } = useUsageFilters();
  const q = { ...query, group_by: by } as typeof query;
  const { data, isLoading } = useQuery({ queryKey: USAGE.summary(q), queryFn: () => traceApi.usage(q), placeholderData: keepPreviousData });
  const rows = data?.rows ?? [];
  const drill = (r: UsageRow) => {
    const key = FILTER_OF[by];
    if (r.key === "none" || filters[key] === r.key) return;
    set({ [key]: r.key });
  };
  const extra = (r: UsageRow) =>
    by === "user" ? (
      <Link to={`/sa/traces?user_id=${r.key}`} onClick={(e) => e.stopPropagation()} className="text-xs font-semibold text-primary underline-offset-2 hover:underline" data-testid={`usage-traces-${r.key}`}>
        {t("usage.toTraces")}
      </Link>
    ) : null;
  return (
    <Card className="grid min-w-0 gap-3 p-3" data-testid="usage-breakdown">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-bold">{t("usage.breakdown")}</h2>
        <span className="text-xs text-muted-foreground">{t("usage.drillHint")}</span>
      </div>
      <div className="-mx-3 overflow-x-auto px-3" role="tablist" aria-label={t("usage.groupBy")}>
        <div className="flex w-max gap-1 rounded-xl bg-muted p-1">
          {GROUPS.map((g) => (
            <button
              key={g}
              type="button"
              role="tab"
              aria-selected={by === g}
              onClick={() => set({ by: g })}
              className={cn("min-h-9 rounded-lg px-3 text-sm font-semibold", by === g ? "bg-card shadow-sm" : "text-muted-foreground hover:text-foreground")}
              data-testid={`usage-tab-${g}`}
            >
              {t(`usage.by.${g}`)}
            </button>
          ))}
        </div>
      </div>
      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : !rows.length ? (
        <EmptyState title={t("usage.empty")} />
      ) : desktop ? (
        <Table
          head={[
            t("usage.col.name"),
            t("usage.col.requests"),
            t("usage.col.tokens"),
            t("usage.col.cache"),
            t("usage.col.errors"),
            t("usage.col.latency"),
            t("usage.col.cost"),
            ...(by === "model" ? [t("usage.col.price")] : []),
          ]}
        >
          {rows.map((r) => (
            <Row key={r.key} testId={`usage-row-${r.key}`} onClick={() => drill(r)}>
              <Cell className="max-w-[260px]">
                <TruncText text={name(by, r)} className="font-semibold" />
                {r.sub && r.sub !== r.name ? <TruncText text={r.sub} mono className="text-muted-foreground" /> : null}
                {extra(r)}
              </Cell>
              <Cell className="num whitespace-nowrap">{compact(r.requests)}</Cell>
              <Cell className="num whitespace-nowrap">{tokens(r)}</Cell>
              <Cell className="num whitespace-nowrap">{cache(r)}</Cell>
              <Cell className={cn("num whitespace-nowrap", r.errors > 0 && "font-semibold text-warning")}>{errors(r)}</Cell>
              <Cell className="num whitespace-nowrap">{latency(r)}</Cell>
              <Cell className="num whitespace-nowrap font-semibold">{usd(r.cost)}</Cell>
              {by === "model" ? <Cell className="num whitespace-nowrap text-muted-foreground">{price(r)}</Cell> : null}
            </Row>
          ))}
        </Table>
      ) : (
        <ul className="grid gap-2">
          {rows.map((r) => (
            <li key={r.key}>
              <div
                role="button"
                tabIndex={0}
                onClick={() => drill(r)}
                onKeyDown={(e) => e.key === "Enter" && drill(r)}
                className="grid min-w-0 gap-1 rounded-2xl border border-border bg-card p-3 text-sm hover:bg-accent"
                data-testid={`usage-row-${r.key}`}
              >
                <div className="flex min-w-0 items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-semibold">{name(by, r)}</span>
                  <span className="shrink-0 font-bold tabular-nums">{usd(r.cost)}</span>
                </div>
                {r.sub && r.sub !== r.name ? <span className="truncate font-mono text-xs text-muted-foreground">{r.sub}</span> : null}
                <span className="text-xs text-muted-foreground">
                  {t("usage.col.requests")} {compact(r.requests)} · {t("usage.col.tokens")} {tokens(r)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {t("usage.col.cache")} {cache(r)} · {t("usage.col.latency")} {latency(r)}
                </span>
                <span className={cn("text-xs", r.errors > 0 ? "font-semibold text-warning" : "text-muted-foreground")}>
                  {t("usage.col.errors")} {errors(r)}
                  {by === "model" ? ` · ${price(r)}` : ""}
                </span>
                {extra(r)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
