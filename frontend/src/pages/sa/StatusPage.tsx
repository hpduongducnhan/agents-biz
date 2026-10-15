import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { systemApi } from "@/features/system/api";
import { SYSTEM } from "@/features/system/keys";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { checkAll, type StatusResult } from "@/lib/status";
import { Badge, Card, CardContent, CardHeader, CardTitle, JsonView, Skeleton } from "@/ui";

import { SendTestCard } from "./SendTestCard";

interface Props {
  check?: () => Promise<StatusResult>;
  intervalMs?: number;
}

export function StatusPage({ check = checkAll, intervalMs = 10_000 }: Props) {
  const t = useT();
  const [result, setResult] = useState<StatusResult | null>(null);
  const [failed, setFailed] = useState(false);
  const { data: detail } = useQuery({ queryKey: SYSTEM.status(), queryFn: () => systemApi.status(), refetchInterval: intervalMs });

  useEffect(() => {
    let alive = true;
    const run = () =>
      check().then(
        (r) => {
          if (alive) {
            setResult(r);
            setFailed(false);
          }
        },
        () => {
          if (alive) setFailed(true);
        },
      );
    void run();
    const timer = setInterval(run, intervalMs);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [check, intervalMs]);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="text-base">{t("sa.status.services")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {failed && (
            <p role="alert" className="text-sm text-destructive">
              {t("sa.status.failed")}
            </p>
          )}
          <ul className="space-y-2">
            {(result?.services ?? []).map((s) => (
              <li key={s.name} className="flex min-w-0 items-center gap-3 rounded-2xl bg-muted px-4 py-3">
                <span data-testid={`light-${s.name}`} data-light={s.light} className={cn("size-3 shrink-0 rounded-full", s.light === "up" ? "bg-positive" : "bg-negative")} />
                <span className="font-semibold">{s.label}</span>
                <span className="ml-auto min-w-0 truncate text-xs text-muted-foreground">{s.detail}</span>
              </li>
            ))}
          </ul>
          <p className="num text-xs text-muted-foreground">{t("sa.status.version", { v: result?.version ?? t("common.none") })}</p>
        </CardContent>
      </Card>
      <Card className="shadow-card" data-testid="status-detail">
        <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
          <CardTitle className="text-base">{t("sa.status.detail")}</CardTitle>
          {detail && (
            <Badge variant={detail.mongo_enabled ? "secondary" : "outline"} data-testid="status-mongo">
              {detail.mongo_enabled ? t("sa.status.mongoOn") : t("sa.status.mongoOff")}
            </Badge>
          )}
        </CardHeader>
        <CardContent>{detail ? <JsonView value={detail} maxHeight={420} /> : <Skeleton className="h-40 w-full" />}</CardContent>
      </Card>
      <SendTestCard className="xl:col-span-2" />
    </div>
  );
}

export default StatusPage;
