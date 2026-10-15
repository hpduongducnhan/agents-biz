import { useQuery } from "@tanstack/react-query";

import { traceApi } from "@/features/agent/api";
import { TRACES } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { JsonView, Skeleton } from "@/ui";

/** Raw HTTP tới provider (header bí mật + trường nhạy cảm đã che ở backend) — xem bằng JsonView (R17). */
export function RawView({ runId, rawId }: { runId: string; rawId: string }) {
  const t = useT();
  const { data, isLoading } = useQuery({ queryKey: TRACES.raw(runId, rawId), queryFn: () => traceApi.raw(runId, rawId) });
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  const item = data?.item;
  if (!item) return null;
  return (
    <div className="grid gap-2" data-testid={`raw-${rawId}`}>
      <p className="break-all font-mono text-xs">
        {item.method} {item.url} · {item.ms ?? "—"} ms{item.response ? ` · ${String((item.response as { status?: number }).status ?? "")}` : ""}
      </p>
      <span className="text-xs font-semibold">{t("trace.request")}</span>
      <JsonView value={item.request} maxHeight={320} defaultDepth={2} />
      <span className="text-xs font-semibold">{t("trace.response")}</span>
      <JsonView value={item.response ?? item.error} maxHeight={320} defaultDepth={2} />
    </div>
  );
}
