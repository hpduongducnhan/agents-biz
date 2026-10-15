import { useQuery } from "@tanstack/react-query";
import { ChevronRight, ClipboardList } from "lucide-react";
import { Link } from "react-router";

import { cn } from "@/lib/cn";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { Card, Skeleton } from "@/ui";

import { tasksApi } from "../api";
import { TASKS } from "../keys";

const MINE = { mine: true, open_only: true, sort: "due", limit: 5, offset: 0 } as const;

/** Thẻ Tổng quan "Việc của tôi": số quá hạn / hôm nay / đang mở + 5 việc gần hạn nhất. */
export default function MyTasksWidget() {
  const t = useT();
  const summary = useQuery({ queryKey: TASKS.summary(), queryFn: () => tasksApi.summary() });
  const list = useQuery({ queryKey: TASKS.list(MINE), queryFn: () => tasksApi.list(MINE) });
  const s = summary.data;
  return (
    <Card className="space-y-3 p-4" data-testid="widget-my-tasks">
      <div className="flex items-center gap-2">
        <ClipboardList className="h-5 w-5 text-brand" aria-hidden />
        <h2 className="flex-1 font-extrabold">{t("tasks.widget.title")}</h2>
        <Link to="/tasks?mine=1" className="inline-flex min-h-11 items-center gap-1 text-sm font-bold text-brand" data-testid="widget-my-tasks-all">
          {t("tasks.widget.all")}
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Link>
      </div>
      {s ? (
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm" data-testid="widget-my-tasks-counts">
          <span className={cn(s.mine_overdue > 0 && "font-bold text-destructive")}>{t("tasks.widget.overdue", { n: s.mine_overdue })}</span>
          <span>{t("tasks.widget.today", { n: s.due_today })}</span>
          <span className="text-muted-foreground">{t("tasks.widget.open", { n: s.mine_open })}</span>
        </p>
      ) : (
        <Skeleton className="h-5 w-48" />
      )}
      {list.data && list.data.items.length === 0 && <p className="text-sm text-muted-foreground">{t("tasks.widget.none")}</p>}
      {list.data && list.data.items.length > 0 && (
        <ul className="divide-y divide-border">
          {list.data.items.map((x) => (
            <li key={x.id}>
              <Link to={`/tasks?mine=1&task=${x.id}`} className="flex min-h-11 items-center gap-3 py-2 text-sm" data-testid={`widget-task-${x.id}`}>
                <span className="min-w-0 flex-1 truncate font-semibold">{x.title}</span>
                <span className={cn("shrink-0 text-xs", x.overdue ? "font-bold text-destructive" : "text-muted-foreground")}>
                  {x.due_at ? fmt(x.due_at, "relative") : t("tasks.noDue")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
