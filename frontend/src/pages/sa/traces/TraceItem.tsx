import { Link } from "react-router";

import type { Span } from "@/features/agent/api";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { Badge, Button } from "@/ui";

import { durationMs, fmtMs } from "../traceUtil";
import { usd } from "../usage/filters";
import { useTraceFilters } from "./filters";

type RunItem = Extract<Span, { kind?: "run" }> & {
  agents?: string[];
  models?: string[];
  cost?: number | null;
  llm_errors?: number;
};

/** Một lượt: chuỗi chuyên gia, user, model, thời lượng, token, chi phí, lỗi; lọc nhanh theo user / phiên. */
export function TraceItem({ run, names }: { run: RunItem; names: Record<string, string> }) {
  const t = useT();
  const { set } = useTraceFilters();
  const usage = (run.usage ?? {}) as Record<string, number>;
  const input = (run.input ?? {}) as { model?: { name?: string } };
  const user = names[`user:${run.user_id}`] ?? run.user_id.slice(0, 8);
  const tenant = run.tenant_id ? names[`tenant:${run.tenant_id}`] : undefined;
  const chain = run.agents?.length ? run.agents.join(" → ") : (names[`agent:${run.agent_id}`] ?? run.name);
  const models = run.models?.length ? run.models.join(", ") : (input.model?.name ?? "—");
  const tokens = (usage.input ?? 0) + (usage.output ?? 0);
  return (
    <li className="grid min-w-0 gap-1.5 rounded-2xl border border-border bg-card p-3" data-testid={`trace-${run.run_id}`}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Link to={`/sa/traces/${run.run_id}`} className="min-w-0 flex-1 truncate font-semibold hover:underline" data-testid={`trace-open-${run.run_id}`}>
          {chain}
        </Link>
        {run.llm_errors ? <Badge variant="outline">{t("trace.llmErrors", { n: run.llm_errors })}</Badge> : null}
        <Badge variant={run.status === "error" ? "destructive" : run.status === "ok" ? "secondary" : "outline"}>{t(`trace.status.${run.status ?? "ok"}`)}</Badge>
      </div>
      <span className="truncate text-xs text-muted-foreground">
        {fmt(run.start)} · {user}
        {tenant ? ` (${tenant})` : ""} · {models} · {fmtMs(durationMs(run))} · {tokens} tok{run.cost != null ? ` · ${usd(run.cost)}` : ""}
      </span>
      {run.error ? <p className="line-clamp-2 break-words font-mono text-xs text-destructive">{run.error}</p> : null}
      <div className="flex flex-wrap gap-1">
        <Button size="sm" variant="ghost" onClick={() => set({ user_id: run.user_id })} data-testid={`trace-by-user-${run.run_id}`}>
          {t("trace.byUser")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => set({ user_id: run.user_id, session_id: run.session_id })} data-testid={`trace-by-session-${run.run_id}`}>
          {t("trace.bySession")}
        </Button>
      </div>
    </li>
  );
}
