import { useState } from "react";

import type { Span } from "@/features/agent/api";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { Badge, Button, JsonView } from "@/ui";

import { RawView } from "./RawView";
import { durationMs, fmtMs } from "./traceUtil";

/** Chi tiết một span: trạng thái, thời gian, token / key (llm), input / output (JsonView), raw HTTP. */
export function SpanDetail({ span }: { span: Span }) {
  const t = useT();
  const [raw, setRaw] = useState<string | null>(null);
  const llm = span.kind === "llm" ? span : null;
  const usage = "usage" in span ? (span.usage as Record<string, number> | undefined) : undefined;
  return (
    <div className="grid min-w-0 gap-3" data-testid="span-detail">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{span.kind}</Badge>
        <span className="min-w-0 truncate font-semibold">{span.name}</span>
        <Badge variant={span.status === "error" ? "destructive" : "outline"}>{t(`trace.status.${span.status ?? "ok"}`)}</Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        {fmt(span.start)} · {t("trace.duration")} {fmtMs(durationMs(span))}
        {llm?.ttft_ms != null ? ` · ${t("trace.ttft", { ms: llm.ttft_ms })}` : ""}
      </p>
      {llm?.masked_hint ? (
        <p className="text-xs" data-testid="span-key">
          {t("trace.key")}: <span className="font-mono">{llm.masked_hint}</span>
        </p>
      ) : null}
      {usage && Object.keys(usage).length ? (
        <p className="text-xs" data-testid="span-usage">
          {t("trace.tokens")}: {Object.entries(usage).map(([k, v]) => `${k} ${v}`).join(" · ")}
        </p>
      ) : null}
      {span.kind === "router" ? <RouterDecision output={span.output as RouterOutput} /> : null}
      {span.error ? <p className="whitespace-pre-wrap rounded-xl bg-destructive/10 p-2 text-xs text-destructive">{span.error}</p> : null}
      <span className="text-xs font-semibold">{t("trace.input")}</span>
      <JsonView value={span.input} maxHeight={360} />
      <span className="text-xs font-semibold">{t("trace.output")}</span>
      <JsonView value={span.output} maxHeight={360} />
      {llm?.raw_ids?.length ? (
        <div className="grid gap-2">
          <span className="text-xs font-semibold">{t("trace.raw")}</span>
          <div className="flex flex-wrap gap-2">
            {llm.raw_ids.map((id, i) => (
              <Button key={id} size="sm" variant={raw === id ? "default" : "outline"} onClick={() => setRaw(raw === id ? null : id)} data-testid={`raw-open-${id}`}>
                HTTP {i + 1}
              </Button>
            ))}
          </div>
          {raw ? <RawView runId={span.run_id} rawId={raw} /> : null}
        </div>
      ) : null}
    </div>
  );
}

type RouterOutput = { steps?: { agent: string; task?: string }[]; clarify?: string | null; fallback?: string; sticky?: string } | undefined;

/** Quyết định của router: bước theo thứ tự + hỏi lại + cờ dự phòng / bám. */
function RouterDecision({ output }: { output: RouterOutput }) {
  const t = useT();
  if (!output) return null;
  const steps = (output.steps ?? []).map((x) => (x.task ? `${x.agent} (${x.task})` : x.agent)).join(" → ");
  return (
    <div className="grid gap-1 rounded-xl border border-border p-2 text-xs" data-testid="router-decision">
      <span className="font-semibold">{t("trace.decision")}</span>
      <span>{steps || "—"}</span>
      {output.clarify ? <span>? {output.clarify}</span> : null}
      {output.fallback ? <Badge variant="outline" className="w-fit">fallback: {output.fallback}</Badge> : null}
      {output.sticky ? <Badge variant="outline" className="w-fit">sticky: {output.sticky}</Badge> : null}
    </div>
  );
}
