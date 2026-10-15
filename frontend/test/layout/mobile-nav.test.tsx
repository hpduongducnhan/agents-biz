// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InstallGuide, InstallHint } from "@/layout/InstallGuide";
import { MobileDock } from "@/layout/MobileDock";
import { NavDrawer } from "@/layout/NavDrawer";
import { usePwaStore } from "@/lib/pwa";
import { useUiStore } from "@/stores/ui.store";

import { me } from "../fixtures";
import { renderPage } from "../render";

const UA = {
  iphone:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
  android:
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
  desktop:
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
};

function setUa(ua: string): void {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(ua);
}

function setStandalone(on: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: on && query.includes("standalone"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  vi.restoreAllMocks();
  setStandalone(false);
  setUa(UA.desktop);
  usePwaStore.setState({ prompt: null });
  useUiStore.setState({
    installGuideOpen: false,
    installHintDismissed: false,
    navGroups: {},
  });
});

describe("MobileDock", () => {
  it("có Trợ lý (link /assistant)", () => {
    renderPage(<MobileDock />);
    expect(screen.getByTestId("mobile-dock")).toBeTruthy();
    expect(screen.getByTestId("dock-assistant").getAttribute("href")).toBe(
      "/assistant",
    );
    expect(screen.getByTestId("dock-assistant").textContent).toBe("Trợ lý");
  });

  it.each(["/assistant", "/assistant/s1"])("ẩn ở %s", (route) => {
    renderPage(<MobileDock />, { route, path: "*" });
    expect(screen.queryByTestId("mobile-dock")).toBeNull();
  });

  it("hiện ở trang khác (/notifications)", () => {
    renderPage(<MobileDock />, { route: "/notifications", path: "*" });
    expect(screen.getByTestId("mobile-dock")).toBeTruthy();
  });

  it("bấm Trợ lý điều hướng tới /assistant", async () => {
    renderPage(<MobileDock />);
    await userEvent.setup().click(screen.getByTestId("dock-assistant"));
    await waitFor(() =>
      expect(screen.getByTestId("where").textContent).toBe("/assistant"),
    );
  });
});

describe("NavDrawer", () => {
  const open = async () => {
    await userEvent.setup().click(screen.getByTestId("nav-open"));
    return screen.findByTestId("nav-drawer");
  };

  it("đóng sẵn; bấm ☰ mở và liệt kê các mục chính", async () => {
    renderPage(<NavDrawer />);
    expect(screen.queryByTestId("nav-drawer")).toBeNull();
    const drawer = await open();
    for (const id of ["overview", "assistant", "notifications", "profile"])
      expect(within(drawer).getByTestId(`nav-${id}`)).toBeTruthy();
    expect(within(drawer).queryByTestId("nav-group-ai")).toBeNull();
  });

  it("bấm một mục: điều hướng và đóng", async () => {
    renderPage(<NavDrawer />);
    const drawer = await open();
    await userEvent.setup().click(within(drawer).getByTestId("nav-notifications"));
    await waitFor(() =>
      expect(screen.getByTestId("where").textContent).toBe("/notifications"),
    );
    await waitFor(() => expect(screen.queryByTestId("nav-drawer")).toBeNull());
  });

  it("drawer-install: đóng ngăn kéo và mở hướng dẫn cài", async () => {
    renderPage(<NavDrawer />);
    const drawer = await open();
    await userEvent.setup().click(within(drawer).getByTestId("drawer-install"));
    expect(useUiStore.getState().installGuideOpen).toBe(true);
    await waitFor(() => expect(screen.queryByTestId("nav-drawer")).toBeNull());
  });

  it("đã chạy như app: không có drawer-install", async () => {
    setStandalone(true);
    renderPage(<NavDrawer />);
    const drawer = await open();
    expect(within(drawer).queryByTestId("drawer-install")).toBeNull();
  });

  it("superadmin thấy nhóm Hệ thống", async () => {
    renderPage(<NavDrawer />, {
      user: me({ is_superadmin: true, permissions: [] }),
    });
    const drawer = await open();
    for (const k of ["observability", "config", "ai"])
      expect(within(drawer).getByTestId(`nav-group-${k}`)).toBeTruthy();
  });
});

describe("InstallGuide", () => {
  const show = () => {
    useUiStore.setState({ installGuideOpen: true });
    return renderPage(<InstallGuide />);
  };
  const selected = (id: string) =>
    screen.getByTestId(`install-tab-${id}`).getAttribute("data-state") ===
    "active";

  it("iPhone UA: tab iOS chọn sẵn, 4 bước", async () => {
    setUa(UA.iphone);
    show();
    await screen.findByTestId("install-guide");
    expect(selected("ios")).toBe(true);
    expect(screen.getByTestId("install-steps-ios").children).toHaveLength(4);
  });

  it("Android UA: tab Android chọn sẵn, 3 bước, không có install-now khi chưa có prompt", async () => {
    setUa(UA.android);
    show();
    await screen.findByTestId("install-guide");
    expect(selected("android")).toBe(true);
    expect(screen.getByTestId("install-steps-android").children).toHaveLength(
      3,
    );
    expect(screen.queryByTestId("install-now")).toBeNull();
  });

  it("máy tính: mặc định iOS; chuyển sang Android được", async () => {
    show();
    await screen.findByTestId("install-guide");
    expect(selected("ios")).toBe(true);
    await userEvent.setup().click(screen.getByTestId("install-tab-android"));
    expect(await screen.findByTestId("install-steps-android")).toBeTruthy();
  });

  it("có prompt: install-now gọi prompt và đóng khi chấp nhận", async () => {
    setUa(UA.android);
    const e = Object.assign(new Event("beforeinstallprompt"), {
      prompt: vi.fn().mockResolvedValue(undefined),
      userChoice: Promise.resolve({ outcome: "accepted" as const }),
    });
    usePwaStore.setState({ prompt: e as never });
    show();
    await userEvent.setup().click(await screen.findByTestId("install-now"));
    await waitFor(() => expect(e.prompt).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(useUiStore.getState().installGuideOpen).toBe(false),
    );
  });

  it("đang chạy như app: hiện install-standalone, không có tab", async () => {
    setStandalone(true);
    show();
    expect(await screen.findByTestId("install-standalone")).toBeTruthy();
    expect(screen.queryByTestId("install-tab-ios")).toBeNull();
  });
});

describe("InstallHint", () => {
  it("hiện; 'Xem cách làm' mở hướng dẫn", async () => {
    renderPage(<InstallHint />);
    expect(screen.getByTestId("install-hint").className).toContain("md:hidden");
    await userEvent.setup().click(screen.getByTestId("install-hint-show"));
    expect(useUiStore.getState().installGuideOpen).toBe(true);
  });

  it("tắt gợi ý: ẩn và lưu vào localStorage", async () => {
    renderPage(<InstallHint />);
    await userEvent.setup().click(screen.getByTestId("install-hint-dismiss"));
    expect(screen.queryByTestId("install-hint")).toBeNull();
    const saved = JSON.parse(localStorage.getItem("bw-ui-v1") ?? "{}") as {
      state: { installHintDismissed: boolean };
    };
    expect(saved.state.installHintDismissed).toBe(true);
  });

  it("đã tắt từ trước → không hiện", () => {
    useUiStore.setState({ installHintDismissed: true });
    renderPage(<InstallHint />);
    expect(screen.queryByTestId("install-hint")).toBeNull();
  });

  it("đang chạy như app → không hiện", () => {
    setStandalone(true);
    renderPage(<InstallHint />);
    expect(screen.queryByTestId("install-hint")).toBeNull();
  });
});
