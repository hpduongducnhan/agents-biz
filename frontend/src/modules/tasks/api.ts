/** API module Tasks — tên op khớp backend; kiểu lấy từ OpenAPI (R7). */
import { call, type OpInput, type OpOutput } from "@/lib/api";

export type Task = OpOutput<"tasks.create">;
export type TaskDetail = OpOutput<"tasks.get">;
export type TaskComment = OpOutput<"tasks.add_comment">;
export type TaskSummary = OpOutput<"tasks.summary">;
export type Person = OpOutput<"tasks.people">[number];
export type TasksQuery = OpInput<"tasks.list">;
export type TaskStatus = Task["status"];
export type TaskPriority = Task["priority"];

export const tasksApi = {
  list: (q: TasksQuery) => call("tasks.list", q),
  get: (task_id: string) => call("tasks.get", { task_id }),
  create: (input: OpInput<"tasks.create">) => call("tasks.create", input),
  update: (input: OpInput<"tasks.update">) => call("tasks.update", input),
  assign: (task_id: string, assignee_id: string | null) => call("tasks.assign", { task_id, assignee_id }),
  setStatus: (task_id: string, status: TaskStatus) => call("tasks.set_status", { task_id, status }),
  remove: (task_id: string) => call("tasks.delete", { task_id }),
  comment: (task_id: string, body: string) => call("tasks.add_comment", { task_id, body }),
  summary: () => call("tasks.summary"),
  people: (q: OpInput<"tasks.people">) => call("tasks.people", q),
};
