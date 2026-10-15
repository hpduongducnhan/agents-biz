// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildNav } from "@/layout/nav";
import { MobileDock } from "@/layout/MobileDock";
import { moduleNav, moduleQuickAdds, moduleWidgets } from "@/modules/access";
import type { Task, TaskDetail } from "@/modules/tasks/api";
import { fromInput, toInput } from "@/modules/tasks/labels";
import TasksPage from "@/modules/tasks/pages/TasksPage";
import MyTasksWidget from "@/modules/tasks/widgets/MyTasksWidget";

import { me, page } from "../fixtures";
import { renderPage, setDesktop, Where } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/modules/tasks/api", () => ({
  tasksApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    assign: vi.fn(),
    setStatus: vi.fn(),
    remove: vi.fn(),
    comment: vi.fn(),
    summary: vi.fn(),
    people: vi.fn(),
  },
}));
const { tasksApi } = await import("@/modules/tasks/api");

const MEMBER = me({ permissions: ["tasks.view", "tasks.edit", "agent.chat"] });
const ADMIN = me({ permissions: ["tasks.view", "tasks.edit", "tasks.delete"] });
const VIEWER = me({ permissions: ["tasks.view"] });

function task(over: Partial<Task> = {}): Task {
  return {
    id: "t1",
    title: "Gọi khách hàng",
    description: "",
    status: "todo",
    priority: "normal",
    due_at: "2026-10-20T10:00:00Z",
    overdue: false,
    assignee: { id: "u2", name: "Lan" },
    created_by: { id: "u1", name: "Sếp" },
    source: "web",
    position: 0,
    comment_count: 0,
    completed_at: null,
    created_at: "2026-10-15T00:00:00Z",
    updated_at: "2026-10-15T00:00:00Z",
    ...over,
  };
}
const detail = (over: Partial<TaskDetail> = {}): TaskDetail => ({ ...task(), comments: [], ...over });
const lastList = () => vi.mocked(tasksApi.list).mock.calls.at(-1)?.[0] as Record<string, unknown>;
const open = (route = "/tasks", user = MEMBER) =>
  renderPage(
    <>
      <TasksPage />
      <Where />
    </>,
    { path: "/tasks", route, user },
  );

beforeEach(() => {
  vi.clearAllMocks();
  setDesktop(false);
  vi.mocked(tasksApi.list).mockResolvedValue(page([task(), task({ id: "t2", title: "Báo cáo", overdue: true, assignee: null, comment_count: 2, source: "agent" })]));
  vi.mocked(tasksApi.get).mockResolvedValue(detail());
  vi.mocked(tasksApi.people).mockResolvedValue([{ id: "u1", name: "Sếp" }, { id: "u2", name: "Lan" }]);
});

describe("TasksPage", () => {
  it("mặc định: việc đang mở; thẻ ở điện thoại, bảng ở desktop", async () => {
    const view = open();
    await waitFor(() => expect(lastList()).toEqual({ open_only: true, limit: 20, offset: 0 }));
    const card = await screen.findByTestId("task-t2");
    expect(card.textContent).toContain("Báo cáo");
    expect(card.textContent).toContain("Chưa giao");
    view.unmount();
    setDesktop(true);
    open();
    expect((await screen.findByTestId("task-t1")).tagName).toBe("TR");
  });

  it("bộ lọc ghi vào URL và gửi đúng query", async () => {
    open("/tasks?view=done&mine=1&due=overdue&q=khách");
    await waitFor(() => expect(lastList()).toEqual({ status: "done", mine: true, due: "overdue", q: "khách", limit: 20, offset: 0 }));
    const u = userEvent.setup();
    await u.click(screen.getByTestId("tasks-view-all"));
    await waitFor(() => expect(lastList()).toEqual({ mine: true, due: "overdue", q: "khách", limit: 20, offset: 0 }));
    await u.selectOptions(screen.getByTestId("tasks-due"), "");
    await u.click(screen.getByTestId("tasks-mine"));
    await waitFor(() => expect(lastList()).toEqual({ q: "khách", limit: 20, offset: 0 }));
    expect(screen.getByTestId("where").textContent).toContain("view=all");
  });

  it("rỗng: phân biệt chưa có việc với không khớp bộ lọc", async () => {
    vi.mocked(tasksApi.list).mockResolvedValue(page([]));
    const view = open();
    expect(await screen.findByText("Chưa có việc nào")).toBeTruthy();
    view.unmount();
    open("/tasks?mine=1");
    expect(await screen.findByText("Không có việc nào khớp bộ lọc")).toBeTruthy();
  });

  it("tạo việc: tiêu đề + ưu tiên + hạn + người làm → mở chi tiết việc mới", async () => {
    vi.mocked(tasksApi.create).mockResolvedValue(task({ id: "t9", title: "Việc mới" }));
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("tasks-new"));
    expect(screen.getByTestId("dialog-submit").hasAttribute("disabled")).toBe(true);
    await u.type(screen.getByTestId("task-form-title"), " Việc mới ");
    await u.selectOptions(screen.getByTestId("task-form-priority"), "urgent");
    await waitFor(() => expect(within(screen.getByTestId("task-form-assignee")).getByRole("option", { name: "Lan" })).toBeTruthy());
    await u.selectOptions(screen.getByTestId("task-form-assignee"), "u2");
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() =>
      expect(tasksApi.create).toHaveBeenCalledWith({ title: "Việc mới", description: "", priority: "urgent", due_at: null, assignee_id: "u2" }),
    );
    expect(toast.success).toHaveBeenCalledWith("Đã tạo việc");
    await waitFor(() => expect(screen.getByTestId("where").textContent).toContain("task=t9"));
  });

  it("viewer: không có nút tạo; mở chi tiết chỉ xem, không xoá được", async () => {
    open("/tasks?task=t1", VIEWER);
    expect(await screen.findByTestId("task-editor")).toBeTruthy();
    expect(screen.queryByTestId("tasks-new")).toBeNull();
    expect(screen.getByTestId("task-status").hasAttribute("disabled")).toBe(true);
    expect(screen.queryByTestId("task-comment-input")).toBeNull();
    expect(screen.queryByTestId("task-delete")).toBeNull();
  });
});

describe("TaskSheet", () => {
  it("đổi trạng thái, giao việc, đổi tiêu đề, bình luận", async () => {
    vi.mocked(tasksApi.get).mockResolvedValue(detail({ comments: [{ id: "c1", task_id: "t1", author: { id: "u1", name: "Sếp" }, body: "Gấp nhé", source: "agent", created_at: "2026-10-15T01:00:00Z" }], comment_count: 1 }));
    vi.mocked(tasksApi.setStatus).mockResolvedValue(task({ status: "done" }));
    vi.mocked(tasksApi.assign).mockResolvedValue(task());
    vi.mocked(tasksApi.update).mockResolvedValue(task());
    vi.mocked(tasksApi.comment).mockResolvedValue({ id: "c2", task_id: "t1", author: null, body: "Ok", source: "web", created_at: "2026-10-15T02:00:00Z" });
    open("/tasks?task=t1");
    const u = userEvent.setup();
    const comments = await screen.findByTestId("task-comments");
    expect(comments.textContent).toContain("Gấp nhé");
    expect(comments.textContent).toContain("Tạo bởi trợ lý");
    await u.selectOptions(screen.getByTestId("task-status"), "done");
    await waitFor(() => expect(tasksApi.setStatus).toHaveBeenCalledWith("t1", "done"));
    await waitFor(() => expect(within(screen.getByTestId("task-assignee")).getByRole("option", { name: "Sếp" })).toBeTruthy());
    await u.selectOptions(screen.getByTestId("task-assignee"), "");
    await waitFor(() => expect(tasksApi.assign).toHaveBeenCalledWith("t1", null));
    const title = screen.getByTestId("task-title");
    await u.clear(title);
    await u.type(title, "Gọi lại khách{Enter}");
    await waitFor(() => expect(tasksApi.update).toHaveBeenCalledWith({ task_id: "t1", title: "Gọi lại khách" }));
    await u.type(screen.getByTestId("task-comment-input"), "Ok");
    await u.click(screen.getByTestId("task-comment-send"));
    await waitFor(() => expect(tasksApi.comment).toHaveBeenCalledWith("t1", "Ok"));
  });

  it("xoá cần xác nhận (quyền tasks.delete) rồi đóng chi tiết", async () => {
    vi.mocked(tasksApi.remove).mockResolvedValue(null as never);
    open("/tasks?task=t1", ADMIN);
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("task-delete"));
    expect(await screen.findByText(/Xoá "Gọi khách hàng" cùng bình luận/)).toBeTruthy();
    await u.click(screen.getByRole("button", { name: "Xoá việc" }));
    await waitFor(() => expect(tasksApi.remove).toHaveBeenCalledWith("t1"));
    expect(toast.success).toHaveBeenCalledWith("Đã xoá việc");
    await waitFor(() => expect(screen.getByTestId("where").textContent).not.toContain("task="));
    await new Promise((r) => setTimeout(r, 50));
    expect(tasksApi.get).toHaveBeenCalledTimes(1); // không tải lại việc vừa xoá (404)
  });

  it("việc không còn (tổ chức khác / đã xoá) → báo không tìm thấy", async () => {
    vi.mocked(tasksApi.get).mockRejectedValue(new Error("404"));
    open("/tasks?task=zzz");
    expect(await screen.findByText("Không tìm thấy công việc")).toBeTruthy();
  });
});

describe("MyTasksWidget + registry", () => {
  it("widget: số quá hạn / hôm nay / đang mở + việc gần hạn", async () => {
    vi.mocked(tasksApi.summary).mockResolvedValue({ todo: 3, doing: 1, done: 0, cancelled: 0, overdue: 2, due_today: 1, mine_open: 2, mine_overdue: 1 });
    vi.mocked(tasksApi.list).mockResolvedValue(page([task({ overdue: true })]));
    renderPage(<MyTasksWidget />, { user: MEMBER });
    const counts = await screen.findByTestId("widget-my-tasks-counts");
    expect(counts.textContent).toContain("1 quá hạn");
    expect(counts.textContent).toContain("2 đang mở");
    expect((await screen.findByTestId("widget-task-t1")).getAttribute("href")).toBe("/tasks?mine=1&task=t1");
    expect(lastList()).toEqual({ mine: true, open_only: true, sort: "due", limit: 5, offset: 0 });
  });

  it("menu / nút thêm nhanh / widget theo quyền", async () => {
    expect(moduleNav(MEMBER).map((n) => n.id)).toEqual(["tasks"]);
    expect(moduleNav(me({ permissions: [] }))).toEqual([]);
    expect(moduleQuickAdds(VIEWER)).toEqual([]);
    expect(moduleWidgets(VIEWER).map((w) => w.id)).toEqual(["my-tasks"]);
    expect(buildNav(MEMBER).find((s) => s.key === "main")?.items.map((i) => i.id)).toEqual(["overview", "tasks", "assistant"]);
    renderPage(<MobileDock />, { user: MEMBER });
    expect(screen.getByTestId("dock-add-task").textContent).toContain("Việc mới");
    expect(screen.getByTestId("dock-assistant")).toBeTruthy();
  });

  it("datetime-local ↔ ISO", () => {
    expect(toInput(null)).toBe("");
    expect(fromInput("")).toBeNull();
    const iso = fromInput("2026-10-20T09:30");
    expect(iso && toInput(iso)).toBe("2026-10-20T09:30");
  });
});
