import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";
import { Field, FormDialog, Input, NativeSelect, Textarea } from "@/ui";

import { type Task, type TaskPriority, tasksApi } from "../api";
import { TASKS } from "../keys";
import { fromInput, PRIORITIES } from "../labels";
import { PeopleSelect } from "./PeopleSelect";

type Props = { open: boolean; onOpenChange: (open: boolean) => void; onCreated?: (task: Task) => void };

/** Tạo việc: tiêu đề, (mô tả), ưu tiên, hạn, người làm — dùng ở trang Công việc và nút "Thêm nhanh". */
export function TaskForm({ open, onOpenChange, onCreated }: Props) {
  const t = useT();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [due, setDue] = useState("");
  const [assignee, setAssignee] = useState("");
  const reset = () => {
    setTitle("");
    setDescription("");
    setPriority("normal");
    setDue("");
    setAssignee("");
  };
  const create = useMutation({
    mutationFn: () =>
      tasksApi.create({ title: title.trim(), description, priority, due_at: fromInput(due), assignee_id: assignee || null }),
    onSuccess: (task) => {
      void qc.invalidateQueries({ queryKey: TASKS.all });
      toast.success(t("tasks.created"));
      reset();
      onOpenChange(false);
      onCreated?.(task);
    },
  });
  const close = (v: boolean) => {
    onOpenChange(v);
    if (!v) create.reset();
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={close}
      title={t("tasks.new")}
      onSubmit={() => create.mutate()}
      submitting={create.isPending}
      disabled={!title.trim()}
      submitLabel={t("tasks.new")}
      error={create.error ? errorText(create.error) : undefined}
    >
      <Field id="tf-title" label={t("tasks.field.title")}>
        <Input id="tf-title" autoFocus maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} data-testid="task-form-title" />
      </Field>
      <Field id="tf-desc" label={t("tasks.field.description")}>
        <Textarea id="tf-desc" rows={3} maxLength={10000} value={description} onChange={(e) => setDescription(e.target.value)} data-testid="task-form-description" />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="tf-due" label={t("tasks.field.due")}>
          <Input id="tf-due" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} data-testid="task-form-due" />
        </Field>
        <Field id="tf-priority" label={t("tasks.field.priority")}>
          <NativeSelect id="tf-priority" value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)} data-testid="task-form-priority">
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {t(`tasks.priority.${p}`)}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </div>
      <Field id="tf-assignee" label={t("tasks.field.assignee")}>
        <PeopleSelect id="tf-assignee" value={assignee} onChange={setAssignee} testId="task-form-assignee" />
      </Field>
    </FormDialog>
  );
}

/** Hộp thoại "Thêm nhanh" của registry (lazy — export default). */
export default function QuickAddTask(props: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return <TaskForm {...props} />;
}
