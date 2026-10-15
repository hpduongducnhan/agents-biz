// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserMenu } from "@/layout/UserMenu";
import { usePwaStore } from "@/lib/pwa";
import { useUiStore } from "@/stores/ui.store";

import { renderPage } from "../render";

vi.mock("@/features/auth/api", () => ({
  authApi: { logout: vi.fn(), me: vi.fn(), updateMe: vi.fn() },
}));

const prompt = (outcome: "accepted" | "dismissed") => {
  const e = new Event("beforeinstallprompt") as Event & {
    prompt: ReturnType<typeof vi.fn>;
    userChoice: Promise<{ outcome: string }>;
  };
  e.prompt = vi.fn().mockResolvedValue(undefined);
  e.userChoice = Promise.resolve({ outcome });
  return e;
};

beforeEach(() => usePwaStore.setState({ prompt: null }));

describe("UserMenu — cài PWA", () => {
  it("chưa có beforeinstallprompt → không có mục cài", async () => {
    renderPage(<UserMenu />);
    await userEvent.setup().click(screen.getByTestId("user-menu"));
    await screen.findByTestId("logout");
    expect(screen.queryByTestId("menu-install")).toBeNull();
  });

  it("có prompt → hiện 'Cài BizWithAgents', bấm gọi prompt, chấp nhận → mục ẩn", async () => {
    const e = prompt("accepted");
    usePwaStore.setState({ prompt: e as never });
    renderPage(<UserMenu />);
    const u = userEvent.setup();
    await u.click(screen.getByTestId("user-menu"));
    const item = await screen.findByTestId("menu-install");
    expect(item.textContent).toContain("Cài BizWithAgents");
    await u.click(item);
    await waitFor(() => expect(e.prompt).toHaveBeenCalledOnce());
    await waitFor(() => expect(usePwaStore.getState().prompt).toBeNull());
    await u.click(screen.getByTestId("user-menu"));
    await screen.findByTestId("logout");
    expect(screen.queryByTestId("menu-install")).toBeNull();
  });
});

describe("UserMenu — hướng dẫn thêm vào màn hình chính", () => {
  beforeEach(() => useUiStore.setState({ installGuideOpen: false }));

  it("có menu-install-guide (md:hidden); bấm mở hướng dẫn", async () => {
    renderPage(<UserMenu />);
    const u = userEvent.setup();
    await u.click(screen.getByTestId("user-menu"));
    const item = await screen.findByTestId("menu-install-guide");
    expect(item.className).toContain("md:hidden");
    await u.click(item);
    expect(useUiStore.getState().installGuideOpen).toBe(true);
  });

  it("menu-install (desktop) chỉ hiện khi có prompt và mang class hidden md:flex", async () => {
    usePwaStore.setState({ prompt: prompt("accepted") as never });
    renderPage(<UserMenu />);
    await userEvent.setup().click(screen.getByTestId("user-menu"));
    expect((await screen.findByTestId("menu-install")).className).toContain(
      "md:flex",
    );
  });

  it("đã chạy như app → không có menu-install-guide", async () => {
    window.matchMedia = ((q: string) => ({
      matches: q.includes("standalone"),
    })) as unknown as typeof window.matchMedia;
    renderPage(<UserMenu />);
    await userEvent.setup().click(screen.getByTestId("user-menu"));
    await screen.findByTestId("logout");
    expect(screen.queryByTestId("menu-install-guide")).toBeNull();
    window.matchMedia = (() => ({
      matches: false,
    })) as unknown as typeof window.matchMedia;
  });
});
