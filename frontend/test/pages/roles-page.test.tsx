// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import RolesPage from "@/pages/admin/RolesPage";

import { me, page, role } from "../fixtures";
import { renderPage, setDesktop } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/rbac/api", () => ({
  rbacApi: { listRoles: vi.fn(), listPermissions: vi.fn(), createRole: vi.fn(), updateRole: vi.fn(), deleteRole: vi.fn() },
}));
const { rbacApi } = await import("@/features/rbac/api");

const CATALOG = [
  { codename: "user.view", domain: "user", description: "Xem danh sách user" },
  { codename: "user.manage", domain: "user", description: "Khoá / mở, gán role" },
  { codename: "tenant.invite", domain: "tenants", description: "Mời người vào tổ chức" },
  { codename: "group.create", domain: "group", description: "Tạo nhóm" },
];
const KT = role({ id: "r-kt", name: "Kế toán", description: "Xem người dùng", is_builtin: false, permissions: ["user.view"], user_count: 2 });
const open = (user = me({ is_superadmin: true, permissions: [] })) => renderPage(<RolesPage />, { path: "/admin/roles", route: "/admin/roles", user });

beforeEach(() => {
  setDesktop(false);
  vi.mocked(rbacApi.listPermissions).mockResolvedValue(CATALOG);
  vi.mocked(rbacApi.listRoles).mockResolvedValue(page([role({ id: "r-admin", name: "admin", permissions: ["user.view", "user.manage", "tenant.invite"] }), role(), KT]));
  vi.mocked(rbacApi.createRole).mockResolvedValue(KT);
  vi.mocked(rbacApi.updateRole).mockResolvedValue(KT);
});

describe("RolesPage", () => {
  it("role có sẵn: chỉ Xem, quyền bị khoá, không lưu được", async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("role-view-admin"));
    expect(screen.queryByTestId("role-edit-admin")).toBeNull();
    expect(screen.queryByTestId("role-delete-admin")).toBeNull();
    expect(await screen.findByTestId("role-builtin-hint")).toBeTruthy();
    expect(screen.getByTestId("perm-user.view").hasAttribute("disabled")).toBe(true);
    expect(screen.getByTestId("dialog-submit").hasAttribute("disabled")).toBe(true);
  });

  it("admin tổ chức (chỉ user.view): xem được, không tạo / sửa / xoá role (role tự tạo dùng chung — D12)", async () => {
    open(me({ permissions: ["user.view"] }));
    expect(await screen.findByTestId("role-view-Kế toán")).toBeTruthy();
    expect(screen.queryByTestId("role-create")).toBeNull();
    expect(screen.queryByTestId("role-edit-Kế toán")).toBeNull();
    expect(screen.queryByTestId("role-delete-Kế toán")).toBeNull();
  });

  it("tạo role: tên, mô tả, tick quyền (kể cả chọn cả nhóm)", async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("role-create"));
    await u.type(screen.getByTestId("role-name"), "Thủ quỹ");
    await u.type(screen.getByTestId("role-description"), "Quản người dùng");
    await u.click(screen.getByRole("checkbox", { name: "Chọn cả nhóm user" }));
    await u.click(screen.getByTestId("perm-tenant.invite"));
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() =>
      expect(rbacApi.createRole).toHaveBeenCalledWith({ name: "Thủ quỹ", description: "Quản người dùng", permissions: ["user.view", "user.manage", "tenant.invite"] }),
    );
  });

  it("sửa role tự tạo", async () => {
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("role-edit-Kế toán"));
    const name = screen.getByTestId("role-name");
    await u.clear(name);
    await u.type(name, "Kế toán trưởng");
    await u.click(screen.getByTestId("perm-group.create"));
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() =>
      expect(rbacApi.updateRole).toHaveBeenCalledWith({ role_id: "r-kt", name: "Kế toán trưởng", description: "Xem người dùng", permissions: ["user.view", "group.create"] }),
    );
  });

  it("xoá role đang được gán (2205) → toast lỗi kèm Mã tra cứu", async () => {
    vi.mocked(rbacApi.deleteRole).mockRejectedValue(new ApiError({ message: "x", status: 409, code: 2205, correlationId: "c-5" }));
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("role-delete-Kế toán"));
    await u.click(await screen.findByRole("button", { name: "Xác nhận" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Role đang được gán cho người dùng, không xoá được", { description: "Mã tra cứu: c-5" }),
    );
    expect(rbacApi.deleteRole).toHaveBeenCalledWith("r-kt");
  });

  it("desktop: bảng, mô tả cắt chữ + Tooltip; điện thoại: thẻ", async () => {
    setDesktop(true);
    const view = open();
    const row = await screen.findByTestId("role-item-Kế toán");
    expect(row.tagName).toBe("TR");
    expect(within(row).getByText("Xem người dùng").className.split(/\s+/)).toEqual(expect.arrayContaining(["block", "truncate"]));
    view.unmount();
    setDesktop(false);
    open();
    expect((await screen.findByTestId("role-item-Kế toán")).tagName).toBe("LI");
  });
});
