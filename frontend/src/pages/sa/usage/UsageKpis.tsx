import type { UsageRow } from "@/features/agent/api";
import { useT } from "@/lib/i18n";
import { Card } from "@/ui";

import { compact, pct, usd } from "./filters";

function Kpi({ label, value, hint, testId, tone }: { label: string; value: string; hint?: string; testId: string; tone?: "warn" }) {
  return (
    <Card className="grid min-w-0 gap-0.5 p-3" data-testid={testId}>
      <span className="truncate text-xs text-muted-foreground">{label}</span>
      <span className={tone === "warn" ? "text-lg font-extrabold tabular-nums text-warning" : "text-lg font-extrabold tabular-nums"}>{value}</span>
      {hint ? <span className="truncate text-xs text-muted-foreground">{hint}</span> : null}
    </Card>
  );
}

/** 6 thẻ tổng của khoảng + bộ lọc đang chọn: chi phí, lượt gọi, token, cache, lỗi, độ trễ. */
export function UsageKpis({ total }: { total: UsageRow | null | undefined }) {
  const t = useT();
  const r = total;
  const input = (r?.input_tokens ?? 0) + (r?.cache_read_tokens ?? 0) + (r?.cache_write_tokens ?? 0);
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6" data-testid="usage-kpis">
      <Kpi testId="kpi-cost" label={t("usage.kpi.cost")} value={usd(r?.cost)} />
      <Kpi testId="kpi-requests" label={t("usage.kpi.requests")} value={compact(r?.requests ?? 0)} />
      <Kpi testId="kpi-tokens" label={t("usage.kpi.tokens")} value={`${compact(input)} / ${compact(r?.output_tokens ?? 0)}`} />
      <Kpi testId="kpi-cache" label={t("usage.kpi.cache")} value={compact(r?.cache_read_tokens ?? 0)} hint={t("usage.kpi.cacheHint", { pct: pct(r?.cache_read_tokens ?? 0, input) })} />
      <Kpi
        testId="kpi-errors"
        label={t("usage.kpi.errors")}
        value={compact(r?.errors ?? 0)}
        hint={t("usage.kpi.errorsHint", { pct: pct(r?.errors ?? 0, r?.requests ?? 0) })}
        tone={(r?.errors ?? 0) > 0 ? "warn" : undefined}
      />
      <Kpi testId="kpi-latency" label={t("usage.kpi.latency")} value={r?.latency_avg_ms != null ? `${compact(r.latency_avg_ms)} ms` : "—"} />
    </div>
  );
}
