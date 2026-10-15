import { mkKeys } from "@/lib/keys";

/** Khớp `invalidates` của backend: `tasks.list` · `tasks.detail` · `tasks.summary`. */
export const TASKS = mkKeys("tasks", {
  list: (q: object = {}) => ["list", q],
  detail: (id: string) => ["detail", id],
  summary: () => ["summary"],
  people: (q: object = {}) => ["people", q],
});
