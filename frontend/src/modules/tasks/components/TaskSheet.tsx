import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useHasPermission } from "@/lib/auth/permissions";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Badge, Button, ConfirmDialog, Field, Input, NativeSelect, Sheet, Skeleton, Textarea } from "@/ui";

import { type TaskDetail, type TaskPriority, type TaskStatus, tasksApi } from "../api";
import { TASKS } from "../keys";
import { fromInput, PRIORITIES, STATUSES, toInput } from "../labels";
import { TASK_PERMS } from "../perms";
import { PeopleSelect } from "./PeopleSelect";

type Props = { taskId: string | null; onClose: () => void };

/** Chi tiết một việc (bottom sheet ở điện thoại): sửa nhanh từng trường, giao việc, đổi trạng thái, bình luận, xoá. */
export function TaskSheet({ taskId, onClose }: Props) {
  const t = useT();
  const [deleting, setDeleting] = useState<string | null>(null); // đang xoá → thôi tải lại (data:changed có thể tới trước phản hồi)
  const { data, isLoading, isError } = useQuery({
    queryKey: TASKS.detail(taskId ?? ""),
    queryFn: () => tasksApi.get(taskId as string),
    enabled: !!taskId && deleting !== taskId,
    retry: false,
  });
  return (
    <Sheet open={!!taskId} onOpenChange={(v) => !v && onClose()} title={data?.title ?? t("nav.tasks")} description={data ? <Meta task={data} /> : ""} testId="task-sheet">
      {isLoading && <Skeleton className="h-48 w-full" />}
      {isError && <p className="text-sm text-muted-foreground">{t("err.10001")}</p>}
      {data && <TaskEditor key={data.id + data.updated_at} task={data} onDeleting={(on) => setDeleting(on ? data.id : null)} onDeleted={onClose} />}
    </Sheet>
  );
}

function Meta({ task }: { task: TaskDetail }) {
  const t = useT();
  return (
    <span className="flex flex-wrap items-center gap-2">
      {t("tasks.createdBy", { name: task.created_by?.name ?? "—", when: fmt(task.created_at, "relative") })}
      {task.source === "agent" && (
        <Badge variant="outline" className="gap-1">
          <Bot className="h-3 w-3" aria-hidden />
          {t("tasks.byAgent")}
        </Badge>
      )}
    </span>
  );
}

function TaskEditor({ task, onDeleting, onDeleted }: { task: TaskDetail; onDeleting: (on: boolean) => void; onDeleted: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const canEdit = useHasPermission(TASK_PERMS.EDIT);
  const canDelete = useHasPermission(TASK_PERMS.DELETE);
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [comment, setComment] = useState("");
  const [confirming, setConfirming] = useState(false);
  const done = () => void qc.invalidateQueries({ queryKey: TASKS.all });
  const opts = { onSuccess: done, onError: (err: unknown) => toastError(err) };
  const update = useMutation({ mutationFn: (patch: Record<string, unknown>) => tasksApi.update({ task_id: task.id, ...patch }), ...opts });
  const status = useMutation({ mutationFn: (s: TaskStatus) => tasksApi.setStatus(task.id, s), ...opts });
  const assign = useMutation({ mutationFn: (id: string) => tasksApi.assign(task.id, id || null), ...opts });
  const send = useMutation({
    mutationFn: () => tasksApi.comment(task.id, comment.trim()),
    onSuccess: () => {
      setComment("");
      done();
    },
    onError: (err: unknown) => toastError(err),
  });
  const remove = useMutation({
    mutationFn: () => tasksApi.remove(task.id),
    onMutate: () => onDeleting(true),
    onSuccess: () => {
      toast.success(t("tasks.deleted"));
      onDeleted(); // đóng chi tiết trước — không tải lại việc vừa xoá (404)
      qc.removeQueries({ queryKey: TASKS.detail(task.id) });
      void qc.invalidateQueries({ queryKey: TASKS.list() });
      void qc.invalidateQueries({ queryKey: TASKS.summary() });
    },
    onError: (err: unknown) => {
      onDeleting(false);
      toastError(err);
    },
  });
  const saveTitle = () => title.trim() && title.trim() !== task.title && update.mutate({ title: title.trim() });

  return (
    <div className="grid gap-4" data-testid="task-editor">
      <Field id="ts-title" label={t("tasks.field.title")}>
        <Input id="ts-title" value={title} maxLength={200} disabled={!canEdit} onChange={(e) => setTitle(e.target.value)} onBlur={saveTitle} onKeyDown={(e) => e.key === "Enter" && saveTitle()} data-testid="task-title" />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field id="ts-status" label={t("tasks.field.status")}>
          <NativeSelect id="ts-status" value={task.status} disabled={!canEdit} onChange={(e) => status.mutate(e.target.value as TaskStatus)} data-testid="task-status">
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`tasks.status.${s}`)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field id="ts-priority" label={t("tasks.field.priority")}>
          <NativeSelect id="ts-priority" value={task.priority} disabled={!canEdit} onChange={(e) => update.mutate({ priority: e.target.value as TaskPriority })} data-testid="task-priority">
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {t(`tasks.priority.${p}`)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <div className="col-span-2 sm:col-span-1">
        <Field id="ts-due" label={t("tasks.field.due")}>
          <Input
            id="ts-due"
            type="datetime-local"
            defaultValue={toInput(task.due_at)}
            disabled={!canEdit}
            onBlur={(e) => e.target.value !== toInput(task.due_at) && update.mutate({ due_at: fromInput(e.target.value) })}
            data-testid="task-due"
          />
        </Field>
        </div>
        <Field id="ts-assignee" label={t("tasks.field.assignee")}>
          <PeopleSelect id="ts-assignee" value={task.assignee?.id ?? ""} disabled={!canEdit} onChange={(id) => assign.mutate(id)} testId="task-assignee" />
        </Field>
      </div>
      <Field id="ts-desc" label={t("tasks.field.description")}>
        <Textarea id="ts-desc" rows={3} value={description} maxLength={10000} disabled={!canEdit} onChange={(e) => setDescription(e.target.value)} onBlur={() => description !== task.description && update.mutate({ description })} data-testid="task-description" />
      </Field>
      <section className="grid gap-2" aria-label={t("tasks.comments")}>
        <h3 className="text-sm font-bold">
          {t("tasks.comments")} · {task.comments.length}
        </h3>
        {task.comments.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("tasks.noComments")}</p>
        ) : (
          <ul className="grid gap-2" data-testid="task-comments">
            {task.comments.map((c) => (
              <li key={c.id} className="rounded-xl bg-muted/60 p-3 text-sm">
                <p className="text-xs font-semibold text-muted-foreground">
                  {c.author?.name ?? "—"} · {fmt(c.created_at, "relative")}
                  {c.source === "agent" ? ` · ${t("tasks.byAgent")}` : ""}
                </p>
                <p className="mt-1 whitespace-pre-wrap break-words">{c.body}</p>
              </li>
            ))}
          </ul>
        )}
        {canEdit && (
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (comment.trim()) send.mutate();
            }}
          >
            <Textarea aria-label={t("tasks.comment")} placeholder={t("tasks.comment")} rows={2} maxLength={4000} value={comment} onChange={(e) => setComment(e.target.value)} data-testid="task-comment-input" />
            <Button type="submit" size="icon" className="shrink-0" aria-label={t("tasks.send")} disabled={!comment.trim() || send.isPending} data-testid="task-comment-send">
              <Send className="h-4 w-4" />
            </Button>
          </form>
        )}
      </section>
      {canDelete && (
        <Button type="button" variant="ghost" className="justify-self-start text-destructive" onClick={() => setConfirming(true)} data-testid="task-delete">
          <Trash2 className="h-4 w-4" />
          {t("tasks.delete")}
        </Button>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("tasks.delete")}
        description={t("tasks.deleteConfirm", { title: task.title })}
        confirmLabel={t("tasks.delete")}
        destructive
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
