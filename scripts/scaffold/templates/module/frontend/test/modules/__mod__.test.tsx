// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { moduleNav } from "@/modules/access";
import type { __Mod__Item } from "@/modules/__mod__/api";
import ListPage from "@/modules/__mod__/pages/ListPage";

import { me, page } from "../fixtures";
import { renderPage, setDesktop, Where } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/modules/__mod__/api", () => ({ __mod__Api: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() } }));
const { __mod__Api } = await import("@/modules/__mod__/api");

const MEMBER = me({ permissions: ["__mod__.view", "__mod__.edit"] });
const ADMIN = me({ permissions: ["__mod__.view", "__mod__.edit", "__mod__.delete"] });
const VIEWER = me({ permissions: ["__mod__.view"] });
const item = (over: Partial<__Mod__Item> = {}): __Mod__Item => ({
  id: "i1",
  title: "Mục một",
  description: "",
  status: "open",
  created_by: { id: "u1", name: "Lan" },
  source: "web",
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
  ...over,
});
const lastList = () => vi.mocked(__mod__Api.list).mock.calls.at(-1)?.[0] as Record<string, unknown>;
const open = (route = "/__route__", user = MEMBER) =>
  renderPage(
    <>
      <ListPage />
      <Where />
    </>,
    { path: "/__route__", route, user },
  );

beforeEach(() => {
  vi.clearAllMocks();
  setDesktop(false);
  vi.mocked(__mod__Api.list).mockResolvedValue(page([item()]));
});

describe("__title_en__ ListPage", () => {
  it("thẻ ở điện thoại, bảng ở desktop; lọc trên URL", async () => {
    const view = open();
    expect((await screen.findByTestId("__mod__-i1")).tagName).toBe("BUTTON");
    expect(lastList()).toEqual({ status: "open", limit: 20, offset: 0 });
    view.unmount();
    setDesktop(true);
    open("/__route__?view=all&mine=1&q=abc");
    expect((await screen.findByTestId("__mod__-i1")).tagName).toBe("TR");
    await waitFor(() => expect(lastList()).toEqual({ mine: true, q: "abc", limit: 20, offset: 0 }));
  });

  it("tạo mới", async () => {
    vi.mocked(__mod__Api.create).mockResolvedValue(item({ id: "i2", title: "Mới" }));
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("__mod__-new"));
    await u.type(screen.getByTestId("__mod__-form-title"), " Mới ");
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() => expect(__mod__Api.create).toHaveBeenCalledWith({ title: "Mới", description: "" }));
    expect(toast.success).toHaveBeenCalledWith("Đã tạo");
  });

  it("sửa trạng thái; xoá cần xác nhận (quyền xoá)", async () => {
    vi.mocked(__mod__Api.update).mockResolvedValue(item({ status: "done" }));
    vi.mocked(__mod__Api.remove).mockResolvedValue(null as never);
    open("/__route__", ADMIN);
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("__mod__-i1"));
    await u.selectOptions(screen.getByTestId("__mod__-form-status"), "done");
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() => expect(__mod__Api.update).toHaveBeenCalledWith({ item_id: "i1", title: "Mục một", description: "", status: "done" }));
    await u.click(await screen.findByTestId("__mod__-i1"));
    await u.click(screen.getByTestId("__mod__-delete"));
    await u.click(await screen.findByRole("button", { name: "Xoá" }));
    await waitFor(() => expect(__mod__Api.remove).toHaveBeenCalledWith("i1"));
  });

  it("viewer chỉ xem; menu theo quyền", async () => {
    open("/__route__", VIEWER);
    expect(await screen.findByTestId("__mod__-i1")).toBeTruthy();
    expect(screen.queryByTestId("__mod__-new")).toBeNull();
    expect(moduleNav(VIEWER).map((n) => n.id)).toContain("__mod__");
    expect(moduleNav(me({ permissions: [] })).map((n) => n.id)).not.toContain("__mod__");
  });
});
