// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { usePageMeta, useUiStore } from "@/stores/ui.store";

describe("ui store", () => {
  it("theme: light / dark ghi data-theme lên <html>; system thì bỏ attribute", () => {
    useUiStore.getState().setTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    useUiStore.getState().setTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("chỉ persist theme + sidebar + nhóm + gợi ý cài", () => {
    useUiStore.getState().setTheme("light");
    const saved = JSON.parse(localStorage.getItem("bw-ui-v1") ?? "{}") as {
      state: object;
    };
    expect(saved.state).toEqual({
      sidebarCollapsed: false,
      theme: "light",
      navGroups: {},
      installHintDismissed: false,
    });
  });

  it("hướng dẫn cài: mở không lưu; tắt gợi ý thì lưu", () => {
    useUiStore.getState().setInstallGuide(true);
    expect(useUiStore.getState().installGuideOpen).toBe(true);
    useUiStore.getState().dismissInstallHint();
    const saved = JSON.parse(localStorage.getItem("bw-ui-v1") ?? "{}") as {
      state: Record<string, unknown>;
    };
    expect(saved.state.installHintDismissed).toBe(true);
    expect(saved.state).not.toHaveProperty("installGuideOpen");
    useUiStore.setState({
      installGuideOpen: false,
      installHintDismissed: false,
    });
  });

  it("tiêu đề trang cho Header", () => {
    usePageMeta.getState().set("Hồ sơ", "Tài khoản");
    expect(usePageMeta.getState()).toMatchObject({
      title: "Hồ sơ",
      subtitle: "Tài khoản",
    });
  });
});
