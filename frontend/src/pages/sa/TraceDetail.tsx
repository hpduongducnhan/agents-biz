import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useParams } from "react-router";

import { type Span, traceApi } from "@/features/agent/api";
import { TRACES } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Button, Card, CardContent, EmptyState, Skeleton } from "@/ui";

import { LogDisabledBanner } from "./LogDisabledBanner";
import { SpanDetail } from "./SpanDetail";
import { SpanTree } from "./SpanTree";
import { buildTree } from "./traceUtil";

/** Một lượt: cây span (mở / gập) + chi tiết span đang chọn. Điện thoại: cây trên, chi tiết dưới. */
export default function TraceDetail() {
  const t = useT();
  const { id = "" } = useParams();
  const { data, isLoading } = useQuery({ queryKey: TRACES.get(id), queryFn: () => traceApi.get(id), enabled: !!id });
  const spans = useMemo(() => data?.spans ?? [], [data]);
  const roots = useMemo(() => buildTree(spans), [spans]);
  const [open, setOpen] = useState<Set<string> | null>(null);
  const [picked, setPicked] = useState<Span | null>(null);
  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (data && !data.enabled) return <LogDisabledBanner />;
  if (!spans.length) return <EmptyState title={t("trace.empty")} />;
  const shown = open ?? new Set(roots.map((r) => r.span.id));
  const all = new Set(spans.map((s) => s.id));
  const selected = picked ?? roots[0]?.span ?? null;
  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card>
        <CardContent className="grid gap-2 pt-4">
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setOpen(all)} data-testid="spans-expand">
              {t("trace.expandAll")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(new Set())} data-testid="spans-collapse">
              {t("trace.collapseAll")}
            </Button>
          </div>
          <SpanTree roots={roots} selected={selected?.id ?? null} onSelect={setPicked} open={shown} setOpen={setOpen} />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-4">{selected ? <SpanDetail span={selected} /> : <p className="text-sm text-muted-foreground">{t("trace.pickSpan")}</p>}</CardContent>
      </Card>
    </div>
  );
}
