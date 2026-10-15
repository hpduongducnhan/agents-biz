import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { type UsageRow, traceApi } from "@/features/agent/api";
import { USAGE } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { type Bar, BarChart, Card, NativeSelect, Skeleton } from "@/ui";

import { compact, METRICS, type Metric, type Range, usd, useUsageFilters } from "./filters";

const pad = (n: number) => String(n).padStart(2, "0");
const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Mốc liên tục từ `since` tới giờ (ngày, hoặc giờ khi khoảng là hôm nay) — ngày / giờ không có lần gọi vẫn có cột 0. */
export function buckets(since: string, range: Range, now = new Date()): string[] {
  const out: string[] = [];
  const d = new Date(since);
  if (range === 1) {
    for (; d <= now; d.setHours(d.getHours() + 1)) out.push(`${dayKey(d)} ${pad(d.getHours())}:00`);
  } else {
    for (; d <= now; d.setDate(d.getDate() + 1)) out.push(dayKey(d));
  }
  return out;
}

const VALUE: Record<Metric, (r: UsageRow) => number> = {
  cost: (r) => r.cost,
  requests: (r) => r.requests,
  tokens: (r) => r.input_tokens + r.cache_read_tokens + r.cache_write_tokens + r.output_tokens,
  errors: (r) => r.errors,
};

/** Biểu đồ cột theo ngày (giờ với "Hôm nay") cho chỉ số chọn được; cùng bộ lọc với cả trang. */
export function UsageChart() {
  const t = useT();
  const { range, query, metric, set, since } = useUsageFilters();
  const groupBy = range === 1 ? "hour" : "day";
  const q = { ...query, group_by: groupBy } as typeof query;
  const { data, isLoading } = useQuery({ queryKey: USAGE.summary(q), queryFn: () => traceApi.usage(q), placeholderData: keepPreviousData });
  const byKey = new Map((data?.rows ?? []).map((r) => [r.key, r]));
  const bars: Bar[] = buckets(since, range).map((k) => {
    const row = byKey.get(k);
    return { label: range === 1 ? k.slice(11, 13) + "h" : k.slice(8, 10) + "/" + k.slice(5, 7), tip: k, value: row ? VALUE[metric](row) : 0 };
  });
  return (
    <Card className="grid min-w-0 gap-2 p-3" data-testid="usage-chart">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-bold">{t("usage.chart")}</h2>
        <NativeSelect aria-label={t("usage.metric")} className="w-40" value={metric} onChange={(e) => set({ metric: e.target.value })} data-testid="usage-metric">
          {METRICS.map((m) => (
            <option key={m} value={m}>
              {t(`usage.metric.${m}`)}
            </option>
          ))}
        </NativeSelect>
      </div>
      {isLoading ? <Skeleton className="h-44 w-full" /> : <BarChart bars={bars} format={metric === "cost" ? usd : compact} testId="usage-bars" />}
    </Card>
  );
}
