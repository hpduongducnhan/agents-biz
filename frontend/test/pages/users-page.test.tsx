// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UsersPage from "@/pages/admin/UsersPage";

import { adminUser, me, page, role } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/admin/api", () => ({ adminApi: { listUsers: vi.fn(), updateUser: vi.fn(), resetPassword: vi.fn() } }));
vi.mock("@/features/rbac/api", () => ({ rbacApi: { listRoles: vi.fn() } }));
const { adminApi } = await import("@/features/admin/api");
const { rbacApi } = await import("@/features/rbac/api");

const ADMIN = me({ permissions: ["user.view", "user.manage", "role.manage"] });
const open = (opts: { route?: string; user?: ReturnType<typeof me> } = {}) =>
  renderPage(<UsersPage />, { path: "/admin/users", route: opts.route ?? "/admin/users", user: opts.user ?? ADMIN });

beforeEach(() => {
  setDesktop(false);
  vi.mocked(adminApi.listUsers).mockResolvedValue(page([adminUser()]));
  vi.mocked(adminApi.updateUser).mockResolvedValue(adminUser());
  vi.mocked(rbacApi.listRoles).mockResolvedValue(page([role(), role({ id: "r-admin", name: "admin", description: "Quản trị" })]));
});

describe("UsersPage", () => {
  it("mở bằng ?q=an → tìm ngay; gõ tìm (debounce) → gọi lại từ trang đầu", async () => {
    open({ route: "/admin/users?q=an" });
    await waitFor(() => expect(adminApi.listUsers).toHaveBeenCalledWith({ q: "an", limit: 20, offset: 0 }));
    const u = userEvent.setup();
    const box = screen.getByTestId("users-search");
    await u.clear(box);
    await u.type(box, "bình");
    await waitFor(() => expect(adminApi.listUsers).toHaveBeenLastCalledWith({ q: "bình", limit: 20, offset: 0 }));
  });

  it("khoá tài khoản: bật / tắt trong hộp sửa → chỉ gửi trường đổi", async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("user-edit-u2"));
    await u.click(screen.getByTestId("user-active"));
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() => expect(adminApi.updateUser).toHaveBeenCalledWith({ user_id: "u2", is_active: false }));
  });

  it("gán role: danh sách role (limit 100) + tick thêm admin", async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("user-edit-u2"));
    const roles = await screen.findByTestId("user-roles");
    await u.click(await within(roles).findByRole("checkbox", { name: "admin" }));
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() => expect(adminApi.updateUser).toHaveBeenCalledWith({ user_id: "u2", role_ids: ["r-member", "r-admin"] }));
  });

  it("đặt lại mật khẩu (≥ 8 ký tự)", async () => {
    vi.mocked(adminApi.resetPassword).mockResolvedValue(adminUser({ must_change_password: true }));
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("user-reset-u2"));
    await u.type(screen.getByTestId("user-reset-password"), "temp-pass-1");
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() => expect(adminApi.resetPassword).toHaveBeenCalledWith({ user_id: "u2", new_password: "temp-pass-1" }));
  });

  it("superadmin: chỉ badge + ghi chú, không có công tắc superadmin; tự sửa mình thì không khoá được", async () => {
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([adminUser({ id: "sa", is_superadmin: true }), adminUser({ id: "u1", email: "u1@test.local" })]));
    open();
    const u = userEvent.setup();
    expect(await screen.findByTestId("user-badge-superadmin")).toBeTruthy();
    await u.click(screen.getByTestId("user-edit-sa"));
    expect(await screen.findByTestId("user-superadmin-hint")).toBeTruthy();
    expect(screen.queryByRole("switch", { name: /superadmin/i })).toBeNull();
    await u.keyboard("{Escape}");
    await u.click(await screen.findByTestId("user-edit-u1"));
    expect((await screen.findByTestId("user-active")).hasAttribute("disabled")).toBe(true);
  });

  it("chỉ có user.view → xem được, không có nút sửa / đặt lại", async () => {
    open({ user: me({ permissions: ["user.view"] }) });
    expect(await screen.findByTestId("user-item-u2")).toBeTruthy();
    expect(screen.queryByTestId("user-edit-u2")).toBeNull();
    expect(screen.queryByTestId("user-reset-u2")).toBeNull();
  });

  it("email / tên rất dài: thẻ xuống dòng (break-all, min-w-0) dưới md; bảng cắt chữ + Tooltip từ md", async () => {
    const email = "nguyen.thi.phuong.thao.hoang.ngoc.bich.rat.dai@mot-ten-mien-rat-dai.example.vn";
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([adminUser({ email, name: "Nguyễn Thị Phương Thảo Hoàng Ngọc Bích" })]));
    const view = open();
    const card = await screen.findByTestId("user-item-u2");
    expect(card.className).toContain("min-w-0");
    expect(within(card).getByText(email).className).toContain("break-all");
    view.unmount();
    setDesktop(true);
    open();
    const row = await screen.findByTestId("user-item-u2");
    expect(row.tagName).toBe("TR");
    expect(within(row).getByText(email).className.split(/\s+/)).toEqual(expect.arrayContaining(["block", "truncate"]));
  });
});
