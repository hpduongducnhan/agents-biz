import type { TaskPriority, TaskStatus } from "./api";

export const STATUSES: TaskStatus[] = ["todo", "doing", "done", "cancelled"];
export const PRIORITIES: TaskPriority[] = ["low", "normal", "high", "urgent"];
export const STATUS_VARIANT: Record<TaskStatus, "outline" | "secondary" | "default" | "destructive"> = {
  todo: "outline",
  doing: "default",
  done: "secondary",
  cancelled: "outline",
};

/** `datetime-local` (giờ máy người dùng) ↔ ISO có offset cho API. */
export function toInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}
