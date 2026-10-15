import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { DatabaseZap } from "lucide-react";

import { traceApi } from "@/features/agent/api";
import { USAGE } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";

import { useUsageFilters } from "./usage/filters";
import { LlmErrors } from "./usage/LlmErrors";
import { UsageBreakdown } from "./usage/UsageBreakdown";
import { UsageChart } from "./usage/UsageChart";
import { UsageFilters } from "./usage/UsageFilters";
import { UsageKpis } from "./usage/UsageKpis";

/** Usage agent (superadmin): ai dùng bao nhiêu, provider / model / nơi gọi / key nào, cache, lỗi, độ trễ, chi phí
 *  ước tính — từ document `agent_llm_calls` (Mongo). Bộ lọc trên URL; Mongo tắt → banner. */
export default function UsagePage() {
  const t = useT();
  const { query } = useUsageFilters();
  const q = { ...query, group_by: "purpose" } as typeof query;
  const { data } = useQuery({ queryKey: USAGE.summary(q), queryFn: () => traceApi.usage(q), placeholderData: keepPreviousData });
  if (data && !data.enabled)
    return (
      <div role="status" data-testid="usage-disabled" className="flex items-start gap-3 rounded-2xl border border-warning/40 bg-warning/10 p-4 text-sm">
        <DatabaseZap className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden />
        <p className="font-bold">{t("usage.disabled")}</p>
      </div>
    );
  return (
    <div className="grid min-w-0 gap-3" data-testid="usage-page">
      <UsageFilters />
      <UsageKpis total={data?.total} />
      <p className="text-xs text-muted-foreground">{t("usage.note")}</p>
      <UsageChart />
      <UsageBreakdown />
      <LlmErrors />
    </div>
  );
}
