// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrgPage from "@/pages/org/OrgPage";

import { invite, me, page, role, tenant } from "../fixtures";
import { renderPage } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/tenant/api", () => ({
  tenantApi: { current: vi.fn(), rename: vi.fn(), invite: vi.fn(), invites: vi.fn(), revokeInvite: vi.fn() },
}));
vi.mock("@/features/rbac/api", () => ({ rbacApi: { listRoles: vi.fn() } }));
const { tenantApi } = await import("@/features/tenant/api");
const { rbacApi } = await import("@/features/rbac/api");

const ADMIN = me({ permissions: ["user.view", "user.manage", "tenant.settings", "tenant.invite"] });
const open = (user = ADMIN) => renderPage(<OrgPage />, { path: "/org", route: "/org", user });

beforeEach(() => {
  vi.mocked(tenantApi.current).mockResolvedValue(tenant());
  vi.mocked(tenantApi.invites).mockResolvedValue([invite()]);
  vi.mocked(rbacApi.listRoles).mockResolvedValue(page([role({ id: "r-admin", name: "admin" }), role(), role({ id: "r-viewer", name: "viewer" })]));
});

describe("OrgPage", () => {
  it("thành viên thường: chỉ xem thông tin, không đổi tên, không thấy lời mời", async () => {
    open(me({ permissions: [] }));
    expect((await screen.findByTestId("org-user-count")).textContent).toBe("3 / 10");
    expect(screen.getByTestId("org-name").hasAttribute("disabled")).toBe(true);
    expect(screen.queryByTestId("org-invites")).toBeNull();
    expect(screen.queryByTestId("org-members")).toBeNull();
    expect(tenantApi.invites).not.toHaveBeenCalled();
  });

  it("admin đổi tên tổ chức", async () => {
    vi.mocked(tenantApi.rename).mockResolvedValue(tenant({ name: "Tổ chức Mới" }));
    open();
    const u = userEvent.setup();
    const name = await screen.findByTestId("org-name");
    expect(screen.getByTestId("org-rename").hasAttribute("disabled")).toBe(true);
    await u.clear(name);
    await u.type(name, "Tổ chức Mới");
    await u.click(screen.getByTestId("org-rename"));
    await waitFor(() => expect(tenantApi.rename).toHaveBeenCalledWith("Tổ chức Mới"));
    expect(toast.success).toHaveBeenCalledWith("Đã lưu");
  });

  it("không giới hạn user → hiện chữ", async () => {
    vi.mocked(tenantApi.current).mockResolvedValue(tenant({ user_limit: 0 }));
    open();
    expect((await screen.findByTestId("org-user-count")).textContent).toBe("3 / không giới hạn");
  });

  it("thu hồi lời mời đang chờ", async () => {
    vi.mocked(tenantApi.revokeInvite).mockResolvedValue(null);
    open();
    const u = userEvent.setup();
    const row = await screen.findByTestId("invite-i1");
    expect(row.textContent).toContain("m***@test.local");
    await u.click(within(row).getByTestId("invite-revoke-i1"));
    await waitFor(() => expect(tenantApi.revokeInvite).toHaveBeenCalledWith("i1"));
    expect(toast.success).toHaveBeenCalledWith("Đã thu hồi lời mời");
  });

  it("mời qua link dùng chung: chọn vai trò viewer, số lần dùng → hiện link một lần", async () => {
    vi.mocked(tenantApi.invites).mockResolvedValue([]);
    vi.mocked(tenantApi.invite).mockResolvedValue(invite({ id: "i2", email: null, link: "http://app/invite/raw", max_uses: 5 }));
    open();
    const u = userEvent.setup();
    expect(await screen.findByText("Chưa có lời mời nào đang chờ")).toBeTruthy();
    await u.click(screen.getByTestId("invite-new"));
    await u.click(screen.getByTestId("invite-mode-link"));
    await u.selectOptions(await screen.findByTestId("invite-role"), "r-viewer");
    expect(within(screen.getByTestId("invite-role")).queryAllByText("member")).toHaveLength(1); // member là mặc định, không lặp
    await u.clear(screen.getByTestId("invite-max-uses"));
    await u.type(screen.getByTestId("invite-max-uses"), "5");
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() => expect(tenantApi.invite).toHaveBeenCalledWith({ email: null, role_id: "r-viewer", days: 7, max_uses: 5 }));
    expect(((await screen.findByTestId("invite-link")) as HTMLInputElement).value).toBe("http://app/invite/raw");
  });

  it("mời qua email: cần email hợp lệ, hạn 1–30 ngày", async () => {
    vi.mocked(tenantApi.invite).mockResolvedValue(invite({ link: "http://app/invite/x" }));
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("invite-new"));
    const submit = screen.getByTestId("dialog-submit");
    expect(submit.hasAttribute("disabled")).toBe(true);
    await u.type(screen.getByTestId("invite-email"), "moi@test.local");
    await u.clear(screen.getByTestId("invite-days"));
    await u.type(screen.getByTestId("invite-days"), "31");
    expect(submit.hasAttribute("disabled")).toBe(true);
    await u.clear(screen.getByTestId("invite-days"));
    await u.type(screen.getByTestId("invite-days"), "3");
    await u.click(submit);
    await waitFor(() => expect(tenantApi.invite).toHaveBeenCalledWith({ email: "moi@test.local", role_id: null, days: 3, max_uses: null }));
  });
});
