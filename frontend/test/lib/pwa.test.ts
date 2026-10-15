// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  installPwa,
  isStandalone,
  platformOf,
  registerPwa,
  usePwaStore,
} from "@/lib/pwa";

type Handler = (e: Event) => void;
const handlers: Record<string, Handler[]> = {};
const register = vi.fn().mockResolvedValue({});

function fire(type: string, event: Event = new Event(type)): void {
  for (const h of handlers[type] ?? []) h(event);
}

function installEvent(outcome: "accepted" | "dismissed") {
  const e = new Event("beforeinstallprompt", { cancelable: true }) as Event & {
    prompt: ReturnType<typeof vi.fn>;
    userChoice: Promise<{ outcome: string }>;
  };
  e.prompt = vi.fn().mockResolvedValue(undefined);
  e.userChoice = Promise.resolve({ outcome });
  return e;
}

beforeEach(() => {
  for (const k of Object.keys(handlers)) delete handlers[k];
  vi.spyOn(window, "addEventListener").mockImplementation(((
    type: string,
    h: Handler,
  ) => {
    (handlers[type] ??= []).push(h);
  }) as typeof window.addEventListener);
  Object.defineProperty(navigator, "serviceWorker", {
    value: { register },
    configurable: true,
  });
  usePwaStore.setState({ prompt: null });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "serviceWorker");
});

describe("registerPwa", () => {
  it("dev (không PROD) không đăng ký service worker", () => {
    vi.stubEnv("PROD", false);
    registerPwa();
    fire("load");
    expect(register).not.toHaveBeenCalled();
    expect(handlers.load).toBeUndefined();
  });

  it("bản build (PROD) đăng ký /sw.js khi trang tải xong; đăng ký lỗi không ném", async () => {
    vi.stubEnv("PROD", true);
    registerPwa();
    fire("load");
    expect(register).toHaveBeenCalledWith("/sw.js");
    register.mockRejectedValueOnce(new Error("sw hỏng"));
    expect(() => fire("load")).not.toThrow();
    await Promise.resolve();
  });

  it("trình duyệt không có serviceWorker → bỏ qua", () => {
    vi.stubEnv("PROD", true);
    Reflect.deleteProperty(navigator, "serviceWorker");
    registerPwa();
    expect(handlers.load).toBeUndefined();
  });

  it("beforeinstallprompt → chặn mini-infobar, giữ vào store; appinstalled → xoá", () => {
    registerPwa();
    const e = installEvent("accepted");
    fire("beforeinstallprompt", e);
    expect(e.defaultPrevented).toBe(true);
    expect(usePwaStore.getState().prompt).toBe(e);
    fire("appinstalled");
    expect(usePwaStore.getState().prompt).toBeNull();
  });
});

describe("installPwa", () => {
  it("chưa có prompt → false", async () => {
    expect(await installPwa()).toBe(false);
  });

  it("đồng ý → gọi prompt, trả true, xoá prompt", async () => {
    const e = installEvent("accepted");
    usePwaStore.setState({ prompt: e as never });
    expect(await installPwa()).toBe(true);
    expect(e.prompt).toHaveBeenCalledOnce();
    expect(usePwaStore.getState().prompt).toBeNull();
  });

  it("từ chối → false, vẫn xoá prompt", async () => {
    usePwaStore.setState({ prompt: installEvent("dismissed") as never });
    expect(await installPwa()).toBe(false);
    expect(usePwaStore.getState().prompt).toBeNull();
  });
});

describe("manifest.webmanifest", () => {
  const manifest = JSON.parse(
    readFileSync(
      resolve(import.meta.dirname, "../../public/manifest.webmanifest"),
      "utf8",
    ),
  );

  it("start_url '/', standalone, có tên", () => {
    expect(manifest).toMatchObject({
      start_url: "/",
      display: "standalone",
      short_name: "BizWithAgents",
    });
    expect(manifest.name).toBeTruthy();
  });

  it("có icon 192 và 512 (png) và icon maskable", () => {
    const sizes = manifest.icons
      .filter((i: { type: string }) => i.type === "image/png")
      .map((i: { sizes: string }) => i.sizes);
    expect(sizes).toEqual(expect.arrayContaining(["192x192", "512x512"]));
    expect(
      manifest.icons.some((i: { purpose: string }) => i.purpose === "maskable"),
    ).toBe(true);
    for (const i of manifest.icons)
      expect(
        readFileSync(
          resolve(import.meta.dirname, "../../public", i.src.slice(1)),
        ).length,
      ).toBeGreaterThan(0);
  });
});

describe("sw.js", () => {
  const sw = readFileSync(
    resolve(import.meta.dirname, "../../public/sw.js"),
    "utf8",
  );

  it("không cache API / socket, chỉ GET cùng origin", () => {
    expect(sw).toMatch(/\(api\|ws\)/);
    expect(sw).toContain('req.method !== "GET"');
    expect(sw).toContain("url.origin !== self.location.origin");
  });
});

describe("platformOf / isStandalone", () => {
  const IPHONE =
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1";
  const ANDROID =
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36";
  const MAC =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15";

  it("iPhone / Android / máy tính", () => {
    expect(platformOf(IPHONE, 5)).toBe("ios");
    expect(platformOf(ANDROID, 5)).toBe("android");
    expect(platformOf("Mozilla/5.0 (X11; Linux x86_64) Chrome/120", 0)).toBe(
      "other",
    );
  });

  it("iPad báo Macintosh nhưng có cảm ứng → ios; Mac thật (không cảm ứng) → other", () => {
    expect(platformOf(MAC, 5)).toBe("ios");
    expect(platformOf(MAC, 0)).toBe("other");
  });

  it("mặc định đọc từ navigator", () => {
    expect(platformOf()).toBe("other");
  });

  it("isStandalone: display-mode standalone hoặc navigator.standalone (iOS)", () => {
    window.matchMedia = ((q: string) => ({
      matches: q.includes("standalone"),
    })) as unknown as typeof window.matchMedia;
    expect(isStandalone()).toBe(true);
    window.matchMedia = (() => ({
      matches: false,
    })) as unknown as typeof window.matchMedia;
    expect(isStandalone()).toBe(false);
    Object.defineProperty(navigator, "standalone", {
      value: true,
      configurable: true,
    });
    expect(isStandalone()).toBe(true);
    Reflect.deleteProperty(navigator, "standalone");
  });
});
