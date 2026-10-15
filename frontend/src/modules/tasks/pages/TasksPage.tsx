import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ClipboardList, MessageSquare, Plus, Search } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { useHasPermission } from "@/lib/auth/permissions";
import { cn } from "@/lib/cn";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { useIsDesktop } from "@/lib/use-media";
import { Badge, Button, Cell, EmptyState, Input, NativeSelect, Row, ServerPagination, Skeleton, Switch, Table, TruncText } from "@/ui";

import { type Task, type TasksQuery, tasksApi } from "../api";
import { TaskForm } from "../components/TaskForm";
import { TaskSheet } from "../components/TaskSheet";
import { TASKS } from "../keys";
import { STATUS_VARIANT } from "../labels";
import { TASK_PERMS } from "../perms";

const VIEWS = ["open", "all", "done"] as const;
const DUES = ["overdue", "today", "week", "none"] as const;
const LIMIT = 20;
type View = (typeof VIEWS)[number];

/** Bộ lọc trên URL (`?view=&mine=1&due=&q=&offset=&task=`) — chia sẻ link, thông báo mở đúng việc. */
function useFilters() {
  const [params, setParams] = useSearchParams();
  const view = (VIEWS as readonly string[]).includes(params.get("view") ?? "") ? (params.get("view") as View) : "open";
  const due = (DUES as readonly string[]).includes(params.get("due") ?? "") ? (params.get("due") as TasksQuery["due"]) : undefined;
  const mine = params.get("mine") === "1";
  const q = params.get("q") ?? "";
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const task = params.get("task");
  const set = (patch: Record<string, string | null>, keepOffset = false) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v) next.set(k, v);
          else next.delete(k);
        }
        if (!keepOffset) next.delete("offset");
        return next;
      },
      { replace: true },
    );
  const query: TasksQuery = {
    ...(view === "open" ? { open_only: true } : view === "done" ? { status: "done" } : {}),
    ...(mine ? { mine: true } : {}),
    ...(due ? { due } : {}),
    ...(q.trim() ? { q: q.trim() } : {}),
    limit: LIMIT,
    offset,
  };
  return { view, due, mine, q, offset, task, set, query, filtered: mine || !!due || !!q.trim() || view !== "open" };
}

function Due({ task }: { task: Task }) {
  const t = useT();
  if (!task.due_at) return <span className="text-muted-foreground">{t("tasks.noDue")}</span>;
  return <span className={cn(task.overdue && "font-semibold text-destructive")}>{fmt(task.due_at, "datetime")}</span>;
}

function StatusBadge({ task }: { task: Task }) {
  const t = useT();
  return (
    <Badge variant={STATUS_VARIANT[task.status]} className={cn(task.status === "cancelled" && "line-through")}>
      {t(`tasks.status.${task.status}`)}
    </Badge>
  );
}

/** `/tasks` — việc của tổ chức: lọc (đang mở / tất cả / xong, của tôi, hạn, tìm), bảng ở desktop / thẻ ở điện thoại (R16). */
export default function TasksPage() {
  const t = useT();
  const desktop = useIsDesktop();
  const canEdit = useHasPermission(TASK_PERMS.EDIT);
  const f = useFilters();
  const [creating, setCreating] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: TASKS.list(f.query), queryFn: () => tasksApi.list(f.query), placeholderData: keepPreviousData });
  const items = data?.items ?? [];
  const open = (id: string) => f.set({ task: id }, true);

  return (
    <div className="space-y-4" data-testid="tasks-page">
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-xl bg-muted p-1" role="tablist" aria-label={t("tasks.field.status")}>
            {VIEWS.map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={f.view === v}
                onClick={() => f.set({ view: v === "open" ? null : v })}
                className={cn("min-h-9 rounded-lg px-3 text-sm font-semibold", f.view === v ? "bg-card shadow-sm" : "text-muted-foreground")}
                data-testid={`tasks-view-${v}`}
              >
                {t(`tasks.view.${v}`)}
              </button>
            ))}
          </div>
          <label className="flex min-h-11 items-center gap-2 text-sm font-semibold">
            <Switch checked={f.mine} onCheckedChange={(v) => f.set({ mine: v ? "1" : null })} data-testid="tasks-mine" />
            {t("tasks.mine")}
          </label>
          {canEdit && (
            <Button className="ml-auto" onClick={() => setCreating(true)} data-testid="tasks-new">
              <Plus className="h-4 w-4" />
              {t("tasks.new")}
            </Button>
          )}
        </div>
        <div className="grid grid-cols-[1fr_auto] gap-2 sm:flex">
          <div className="relative min-w-0 flex-1 sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" aria-label={t("tasks.search")} placeholder={t("tasks.search")} value={f.q} onChange={(e) => f.set({ q: e.target.value || null })} data-testid="tasks-search" />
          </div>
          <NativeSelect aria-label={t("tasks.field.due")} className="w-36" value={f.due ?? ""} onChange={(e) => f.set({ due: e.target.value || null })} data-testid="tasks-due">
            <option value="">{t("tasks.due.any")}</option>
            {DUES.map((d) => (
              <option key={d} value={d}>
                {t(`tasks.due.${d}`)}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : items.length === 0 ? (
        <EmptyState icon={<ClipboardList className="h-10 w-10" />} title={t(f.filtered ? "tasks.emptyFiltered" : "tasks.empty")} />
      ) : desktop ? (
        <Table head={[t("tasks.field.title"), t("tasks.field.status"), t("tasks.field.priority"), t("tasks.field.due"), t("tasks.field.assignee"), ""]}>
          {items.map((x) => (
            <Row key={x.id} testId={`task-${x.id}`} onClick={() => open(x.id)} className="cursor-pointer">
              <Cell className="max-w-[360px] font-semibold">
                <TruncText text={x.title} />
              </Cell>
              <Cell>
                <StatusBadge task={x} />
              </Cell>
              <Cell className="whitespace-nowrap">{t(`tasks.priority.${x.priority}`)}</Cell>
              <Cell className="whitespace-nowrap">
                <Due task={x} />
              </Cell>
              <Cell className="max-w-[180px]">
                <TruncText text={x.assignee?.name ?? t("tasks.unassigned")} />
              </Cell>
              <Cell className="w-16 text-right text-muted-foreground">
                {x.comment_count > 0 && (
                  <span className="inline-flex items-center gap-1 text-xs">
                    <MessageSquare className="h-3.5 w-3.5" aria-hidden />
                    {x.comment_count}
                  </span>
                )}
              </Cell>
            </Row>
          ))}
        </Table>
      ) : (
        <ul className="space-y-2">
          {items.map((x) => (
            <li key={x.id}>
              <button
                type="button"
                onClick={() => open(x.id)}
                className="grid w-full min-w-0 gap-1.5 rounded-2xl border border-border bg-card p-4 text-left shadow-card"
                data-testid={`task-${x.id}`}
              >
                <span className="flex min-w-0 items-start gap-2">
                  <span className="min-w-0 flex-1 break-words font-bold">{x.title}</span>
                  <StatusBadge task={x} />
                </span>
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <Due task={x} />
                  <span>{x.assignee?.name ?? t("tasks.unassigned")}</span>
                  {x.priority !== "normal" && <span>{t(`tasks.priority.${x.priority}`)}</span>}
                  {x.comment_count > 0 && (
                    <span className="inline-flex items-center gap-1">
                      <MessageSquare className="h-3.5 w-3.5" aria-hidden />
                      {x.comment_count}
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {data && data.total > LIMIT && <ServerPagination offset={f.offset} limit={LIMIT} total={data.total} onChange={(o) => f.set({ offset: o ? String(o) : null }, true)} />}
      <TaskForm open={creating} onOpenChange={setCreating} onCreated={(task) => open(task.id)} />
      <TaskSheet taskId={f.task} onClose={() => f.set({ task: null }, true)} />
    </div>
  );
}
