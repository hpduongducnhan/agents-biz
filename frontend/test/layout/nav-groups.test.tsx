// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildNav, sectionEntries } from "@/layout/nav";
import { NavDrawer } from "@/layout/NavDrawer";
import { Sidebar } from "@/layout/Sidebar";
import { UserMenu } from "@/layout/UserMenu";
import { useUiStore } from "@/stores/ui.store";

import { me } from "../fixtures";
import { renderPage } from "../render";

vi.mock("@/features/auth/api", () => ({
  authApi: { logout: vi.fn(), me: vi.fn(), updateMe: vi.fn() },
}));
vi.mock("@/features/notifications/api", () => ({
  notificationsApi: {
    unreadCount: vi.fn().mockResolvedValue({ count: 0 }),
    list: vi
      .fn()
      .mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 }),
  },
  markReadFast: vi.fn(),
}));

const SA = me({ is_superadmin: true, permissions: [] });
const GROUPS = {
  observability: ["status", "events", "issues", "mail"],
  config: ["settings", "tenants"],
  ai: ["studio", "traces", "usage", "chat-guard", "ai-settings"],
} as const;
const ALL = Object.values(GROUPS).flat();

beforeEach(() =>
  useUiStore.setState({ navGroups: {}, sidebarCollapsed: false }),
);

describe("buildNav — nhóm con của Hệ thống", () => {
  it("section sa không có mục trực tiếp, 3 nhóm đúng thứ tự và mục", () => {
    const sa = buildNav(SA).find((s) => s.key === "sa");
    expect(sa?.items).toEqual([]);
    expect(sa?.groups?.map((g) => g.key)).toEqual([
      "observability",
      "config",
      "ai",
    ]);
    expect(sa?.groups?.map((g) => g.items.map((i) => i.id))).toEqual([
      [...GROUPS.observability],
      [...GROUPS.config],
      [...GROUPS.ai],
    ]);
    expect(sa && sectionEntries(sa).map((i) => i.id)).toEqual(ALL);
  });

  it("mục ai-settings là mục cuối nhóm AI, trỏ /sa/ai-settings; người thường không thấy", () => {
    const ai = buildNav(SA).find((s) => s.key === "sa")?.groups?.find((g) => g.key === "ai");
    const last = ai?.items[ai.items.length - 1];
    expect(last).toMatchObject({ id: "ai-settings", to: "/sa/ai-settings", label: "nav.aiSettings" });
    const ids = buildNav(me()).flatMap((s) => sectionEntries(s).map((i) => i.id));
    expect(ids).not.toContain("ai-settings");
  });

  it("người thường: không có section sa", () => {
    expect(buildNav(me()).find((s) => s.key === "sa")).toBeUndefined();
  });
});

describe("Sidebar — nhóm gập / mở", () => {
  it("ở '/' mọi nhóm gập; có 3 nút nhóm với aria-expanded=false", () => {
    renderPage(<Sidebar />, { user: SA });
    for (const k of Object.keys(GROUPS)) {
      expect(
        screen.getByTestId(`nav-group-${k}`).getAttribute("aria-expanded"),
      ).toBe("false");
      expect(screen.queryByTestId(`nav-group-${k}-items`)).toBeNull();
    }
    for (const id of ALL) expect(screen.queryByTestId(`nav-${id}`)).toBeNull();
  });

  it("tự mở nhóm chứa route hiện tại, nhóm khác vẫn gập", () => {
    renderPage(<Sidebar />, { user: SA, route: "/sa/traces", path: "*" });
    expect(
      screen.getByTestId("nav-group-ai").getAttribute("aria-expanded"),
    ).toBe("true");
    const items = screen.getByTestId("nav-group-ai-items");
    for (const id of GROUPS.ai)
      expect(within(items).getByTestId(`nav-${id}`)).toBeTruthy();
    expect(
      screen.getByTestId("nav-group-config").getAttribute("aria-expanded"),
    ).toBe("false");
    expect(
      screen
        .getByTestId("nav-group-observability")
        .getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("bấm tiêu đề mở / gập và lưu vào store (kể cả gập nhóm đang chứa route)", async () => {
    const u = userEvent.setup();
    renderPage(<Sidebar />, { user: SA, route: "/sa/status", path: "*" });
    expect(
      screen
        .getByTestId("nav-group-observability")
        .getAttribute("aria-expanded"),
    ).toBe("true");
    await u.click(screen.getByTestId("nav-group-observability"));
    expect(useUiStore.getState().navGroups.observability).toBe(false);
    expect(screen.queryByTestId("nav-status")).toBeNull();
    await u.click(screen.getByTestId("nav-group-config"));
    expect(useUiStore.getState().navGroups.config).toBe(true);
    expect(screen.getByTestId("nav-settings")).toBeTruthy();
    expect(
      screen.getByTestId("nav-group-config").getAttribute("aria-expanded"),
    ).toBe("true");
  });

  it("trạng thái đã lưu thắng quy tắc 'chứa route'", () => {
    useUiStore.setState({ navGroups: { ai: true, observability: false } });
    renderPage(<Sidebar />, { user: SA, route: "/sa/status", path: "*" });
    expect(
      screen.getByTestId("nav-group-ai").getAttribute("aria-expanded"),
    ).toBe("true");
    expect(
      screen
        .getByTestId("nav-group-observability")
        .getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("sidebar thu gọn: mọi mục của mọi nhóm hiện phẳng (icon), không có nút nhóm", () => {
    useUiStore.setState({ sidebarCollapsed: true });
    renderPage(<Sidebar />, { user: SA });
    for (const [k, ids] of Object.entries(GROUPS)) {
      const wrap = screen.getByTestId(`nav-group-${k}`);
      expect(wrap.tagName).not.toBe("BUTTON");
      for (const id of ids)
        expect(within(wrap).getByTestId(`nav-${id}`)).toBeTruthy();
    }
  });

  it("người thường: không có nav-group-*", () => {
    renderPage(<Sidebar />, { user: me() });
    expect(screen.queryByTestId("nav-group-ai")).toBeNull();
    expect(screen.queryByTestId("nav-group-config")).toBeNull();
    expect(screen.queryByTestId("nav-group-observability")).toBeNull();
  });
});

describe("NavDrawer — nhóm con (điện thoại)", () => {
  const open = async () => {
    await userEvent.setup().click(screen.getByTestId("nav-open"));
    return screen.findByTestId("nav-drawer");
  };

  it("superadmin: 3 nút nhóm Hệ thống; mở từng nhóm thấy đủ 7 mục", async () => {
    renderPage(<NavDrawer />, { user: SA });
    const drawer = await open();
    for (const [k, ids] of Object.entries(GROUPS)) {
      const btn = within(drawer).getByTestId(`nav-group-${k}`);
      if (btn.getAttribute("aria-expanded") !== "true")
        await userEvent.setup().click(btn);
      for (const id of ids)
        expect(within(drawer).getByTestId(`nav-${id}`)).toBeTruthy();
    }
  });

  it("chọn một mục điều hướng tới route của nó và đóng ngăn kéo", async () => {
    renderPage(<NavDrawer />, { user: SA, route: "/sa/status", path: "*" });
    const drawer = await open();
    const u = userEvent.setup();
    const g = within(drawer).getByTestId("nav-group-ai");
    if (g.getAttribute("aria-expanded") !== "true") await u.click(g);
    await u.click(within(drawer).getByTestId("nav-usage"));
    await waitFor(() => expect(screen.queryByTestId("nav-drawer")).toBeNull());
  });

  it("người thường: không có nav-group-*", async () => {
    renderPage(<NavDrawer />, { user: me() });
    const drawer = await open();
    expect(drawer.querySelector('[data-testid^="nav-group-"]')).toBeNull();
    expect(within(drawer).queryByTestId("nav-usage")).toBeNull();
  });
});

describe("UserMenu — không còn mục điều hướng", () => {
  it("superadmin: không có menu-group-* và menu-<id> của trang hệ thống", async () => {
    renderPage(<UserMenu />, { user: SA });
    await userEvent.setup().click(screen.getByTestId("user-menu"));
    await screen.findByTestId("logout");
    expect(document.querySelector('[data-testid^="menu-group-"]')).toBeNull();
    for (const id of ALL) expect(screen.queryByTestId(`menu-${id}`)).toBeNull();
  });
});

describe("Mục Chống spam trợ lý", () => {
  it("nằm trong nhóm AI, trỏ /sa/chat-guard", () => {
    const sa = buildNav(SA).find((s) => s.key === "sa");
    const item = sa && sectionEntries(sa).find((i) => i.id === "chat-guard");
    expect(item?.to).toBe("/sa/chat-guard");
    expect(sa?.groups?.find((g) => g.key === "ai")?.items.map((i) => i.id)).toContain("chat-guard");
  });
});
