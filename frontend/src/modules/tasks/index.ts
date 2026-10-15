/** Manifest module Tasks (D25) — menu, trang, "Thêm nhanh", widget Tổng quan, từ điển. */
import { ClipboardList, ListPlus } from "lucide-react";
import { lazy } from "react";

import type { ModuleManifest } from "../types";
import { tasksDict } from "./dict";
import { TASK_PERMS } from "./perms";

export const tasksModule: ModuleManifest = {
  id: "tasks",
  nav: [{ id: "tasks", to: "/tasks", label: "nav.tasks", icon: ClipboardList, perm: TASK_PERMS.VIEW }],
  routes: [{ path: "tasks", title: "nav.tasks", subtitle: "sub.tasks", perm: TASK_PERMS.VIEW, component: lazy(() => import("./pages/TasksPage")) }],
  quickAdd: [{ id: "task", label: "tasks.quickAdd", icon: ListPlus, perm: TASK_PERMS.EDIT, dialog: lazy(() => import("./components/TaskForm")) }],
  widgets: [{ id: "my-tasks", perm: TASK_PERMS.VIEW, component: lazy(() => import("./widgets/MyTasksWidget")) }],
  dict: tasksDict,
};
