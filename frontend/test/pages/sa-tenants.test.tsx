// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MailOutboxPage from "@/pages/sa/MailOutboxPage";
import TenantsPage from "@/pages/sa/TenantsPage";

import { me, page, tenant } from "../fixtures";
import { renderPage, setDesktop } from "../render";
import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/tenant/api", () => ({
  tenantsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), suspend: vi.fn(), resume: vi.fn() },
  mailApi: { outbox: vi.fn() },
}));
const { tenantsApi, mailApi } = await import("@/features/tenant/api");

const SA = me({ is_superadmin: true, permissions: [] });
const ACME = tenant({ id: "t2", name: "Acme", slug: "acme", user_count: 2, user_limit: 0, policies: { user_limit: null } });
const open = () => renderPage(<TenantsPage />, { path: "/sa/tenants", route: "/sa/tenants", user: SA });

beforeEach(() => {
  setDesktop(false);
  vi.mocked(tenantsApi.list).mockResolvedValue(page([tenant(), ACME]));
});

describe("TenantsPage (superadmin)", () => {
  it("điện thoại: thẻ có số user / hạn mức; desktop: bảng", async () => {
    const view = open();
    const card = await screen.findByTestId("tenant-acme");
    expect(card.tagName).toBe("LI");
    expect(card.textContent).toContain("2 / không giới hạn");
    view.unmount();
    setDesktop(true);
    open();
    expect((await screen.findByTestId("tenant-to-chuc-mot")).tagName).toBe("TR");
  });

  it("tìm kiếm gửi q; rỗng → trạng thái trống", async () => {
    vi.mocked(tenantsApi.list).mockResolvedValue(page([]));
    open();
    expect(await screen.findByText("Chưa có tổ chức nào")).toBeTruthy();
    await userEvent.setup().type(screen.getByTestId("tenants-search"), "ac");
    await waitFor(() => expect(tenantsApi.list).toHaveBeenLastCalledWith({ q: "ac", limit: 100 }));
  });

  it("tạo tổ chức + mời admin đầu tiên, hạn mức user", async () => {
    vi.mocked(tenantsApi.create).mockResolvedValue({ tenant: ACME, invite: null });
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("tenant-create"));
    await u.type(screen.getByTestId("tenant-name"), "Acme");
    await u.type(screen.getByTestId("tenant-admin-email"), "boss@acme.io");
    await u.type(screen.getByTestId("tenant-user-limit"), "abc");
    expect(screen.getByTestId("dialog-submit").hasAttribute("disabled")).toBe(true);
    await u.clear(screen.getByTestId("tenant-user-limit"));
    await u.type(screen.getByTestId("tenant-user-limit"), "25");
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() =>
      expect(tenantsApi.create).toHaveBeenCalledWith({ name: "Acme", admin_email: "boss@acme.io", policies: { user_limit: 25, agent_enabled: null } }),
    );
    expect(toast.success).toHaveBeenCalledWith("Đã tạo tổ chức");
  });

  it("sửa: tắt trợ lý AI, bỏ hạn mức riêng", async () => {
    vi.mocked(tenantsApi.update).mockResolvedValue(ACME);
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("tenant-edit-acme"));
    await u.click(screen.getByTestId("tenant-agent-enabled"));
    await u.click(screen.getByTestId("dialog-submit"));
    await waitFor(() =>
      expect(tenantsApi.update).toHaveBeenCalledWith({ tenant_id: "t2", name: "Acme", policies: { user_limit: null, agent_enabled: false } }),
    );
  });

  it("khoá cần xác nhận; tổ chức đang khoá → mở khoá ngay", async () => {
    vi.mocked(tenantsApi.list).mockResolvedValue(page([tenant(), tenant({ ...ACME, status: "suspended" })]));
    vi.mocked(tenantsApi.suspend).mockResolvedValue(tenant({ status: "suspended" }));
    vi.mocked(tenantsApi.resume).mockResolvedValue({ ...ACME, status: "active" });
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("tenant-toggle-to-chuc-mot"));
    expect(await screen.findByText(/Khoá Tổ chức Một\?/)).toBeTruthy();
    await u.click(screen.getByRole("button", { name: "Khoá" }));
    await waitFor(() => expect(tenantsApi.suspend).toHaveBeenCalledWith("t1"));
    expect(toast.success).toHaveBeenCalledWith("Đã khoá tổ chức");
    await u.click(screen.getByTestId("tenant-toggle-acme"));
    await waitFor(() => expect(tenantsApi.resume).toHaveBeenCalledWith("t2"));
    expect(toast.success).toHaveBeenCalledWith("Đã mở khoá tổ chức");
  });
});

describe("MailOutboxPage", () => {
  const outbox = () => renderPage(<MailOutboxPage />, { path: "/sa/mail", route: "/sa/mail", user: SA });

  it("console: liệt kê thư", async () => {
    vi.mocked(mailApi.outbox).mockResolvedValue({
      enabled: true,
      items: [{ id: "m1", to: "an@test.local", subject: "Xác thực email", text: "Mở link http://app/verify-email?token=x", html: null, sent_at: "2026-10-15T01:00:00Z" }],
    });
    outbox();
    const list = await screen.findByTestId("mail-outbox");
    expect(list.textContent).toContain("Xác thực email");
    expect(list.textContent).toContain("an@test.local");
    expect(list.textContent).toContain("verify-email?token=x");
  });

  it("SMTP thật → báo không có hộp thư; console rỗng → trạng thái trống", async () => {
    vi.mocked(mailApi.outbox).mockResolvedValue({ enabled: false, items: [] });
    const view = outbox();
    expect(await screen.findByTestId("mail-disabled")).toBeTruthy();
    view.unmount();
    vi.mocked(mailApi.outbox).mockResolvedValue({ enabled: true, items: [] });
    outbox();
    expect(await screen.findByText("Chưa có thư nào")).toBeTruthy();
  });
});
