// @vitest-environment jsdom
import type { AxiosAdapter, InternalAxiosRequestConfig } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, call, configureHttp, endpoint } from "@/lib/api";
import { http } from "@/lib/api/client";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "@/lib/auth-tokens";

type Reply = { status: number; data: unknown; headers?: Record<string, string> };

function adapter(route: (cfg: InternalAxiosRequestConfig) => Reply): AxiosAdapter {
  return async (cfg) => {
    const r = route(cfg);
    const response = { data: r.data, status: r.status, statusText: "", headers: r.headers ?? {}, config: cfg };
    if (r.status >= 400) throw Object.assign(new Error(`HTTP ${r.status}`), { config: cfg, response, isAxiosError: true });
    return response;
  };
}

const ok = (data: unknown) => ({ status: 200, data: { success: true, code: 0, message: "OK", data, correlation_id: "c-ok" } });
const fail = (status: number, code: number, cid = "c-err") => ({
  status,
  data: { success: false, code, message: `err ${code}`, data: null, correlation_id: cid },
});
const isRefresh = (cfg: InternalAxiosRequestConfig) => !!cfg.url?.endsWith("auth/refresh");

afterEach(() => {
  clearTokens();
  vi.unstubAllGlobals();
});

describe("http — envelope (R6)", () => {
  it("mở envelope; lỗi HTTP thành ApiError có correlation id", async () => {
    configureHttp({ baseURL: "http://t/api", adapter: adapter((cfg) => (cfg.url === "a" ? ok({ n: 1 }) : fail(409, 2101, "cid-409"))) });
    expect(await http.get("a")).toEqual({ n: 1 });
    const err = await http.post("b", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: 2101, correlationId: "cid-409" });
  });

  it("HTTP 200 nhưng success=false vẫn là ApiError", async () => {
    configureHttp({ baseURL: "http://t/api", adapter: adapter(() => ({ status: 200, data: { success: false, code: 1002, message: "sai", data: null, correlation_id: "c2" } })) });
    expect(await http.get("x").catch((e: unknown) => e)).toMatchObject({ code: 1002, correlationId: "c2" });
  });

  it("gắn Accept-Language theo <html lang>", async () => {
    document.documentElement.lang = "en";
    let lang: unknown;
    configureHttp({ baseURL: "http://t/api", adapter: adapter((cfg) => ((lang = cfg.headers["Accept-Language"]), ok(1))) });
    await http.get("x");
    expect(lang).toBe("en");
    document.documentElement.lang = "vi";
  });
});

describe("token", () => {
  it("access token chỉ ở bộ nhớ — localStorage chỉ có refresh token", () => {
    setTokens("acc-123", "ref-456");
    expect(getAccessToken()).toBe("acc-123");
    expect(localStorage.length).toBe(1);
    expect(localStorage.key(0)).toBe("bw_refresh_token");
    expect(localStorage.getItem("bw_refresh_token")).toBe("ref-456");
  });
});

describe("refresh", () => {
  it("nhiều request cùng 401 → refresh đúng một lần, cả ba gửi lại thành công", async () => {
    setTokens("old", "r1");
    let refreshes = 0;
    configureHttp({
      baseURL: "http://t/api",
      adapter: adapter((cfg) => {
        if (isRefresh(cfg)) return (refreshes++, ok({ access_token: "new", refresh_token: "r2" }));
        return cfg.headers.Authorization === "Bearer new" ? ok("done") : fail(401, 1004);
      }),
    });
    expect(await Promise.all([http.get("x"), http.get("y"), http.get("z")])).toEqual(["done", "done", "done"]);
    expect(refreshes).toBe(1);
    expect(getAccessToken()).toBe("new");
    expect(getRefreshToken()).toBe("r2");
  });

  it("refresh hỏng → xoá phiên, báo onAuthFailure đúng một lần", async () => {
    setTokens("old", "gone");
    const onAuthFailure = vi.fn();
    configureHttp({ baseURL: "http://t/api", onAuthFailure, adapter: adapter((cfg) => (isRefresh(cfg) ? fail(401, 2104) : fail(401, 1004))) });
    const errors = await Promise.all([http.get("x").catch((e: unknown) => e), http.get("y").catch((e: unknown) => e)]);
    expect(errors.every((e) => e instanceof ApiError && e.status === 401)).toBe(true);
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });

  it("refresh lỗi mạng (không có response) → giữ token, KHÔNG gọi onAuthFailure, request ném ApiError status 0", async () => {
    setTokens("old", "keep");
    const onAuthFailure = vi.fn();
    const net: AxiosAdapter = async (cfg) => {
      if (isRefresh(cfg)) throw Object.assign(new Error("Network Error"), { config: cfg, isAxiosError: true });
      const r = fail(401, 1004);
      throw Object.assign(new Error("HTTP 401"), { config: cfg, response: { data: r.data, status: 401, statusText: "", headers: {}, config: cfg }, isAxiosError: true });
    };
    configureHttp({ baseURL: "http://t/api", onAuthFailure, adapter: net });
    const err = await http.get("x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(getRefreshToken()).toBe("keep");
  });

  it("refresh trả 5xx → giữ token, không onAuthFailure", async () => {
    setTokens("old", "keep5");
    const onAuthFailure = vi.fn();
    configureHttp({ baseURL: "http://t/api", onAuthFailure, adapter: adapter((cfg) => (isRefresh(cfg) ? fail(503, 1000) : fail(401, 1004))) });
    await http.get("x").catch((e: unknown) => e);
    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(getRefreshToken()).toBe("keep5");
  });

  it("hai tab: refresh xếp hàng qua Web Locks và đọc refresh token MỚI NHẤT trong khoá", async () => {
    setTokens("old", "r1");
    const sent: string[] = [];
    let release!: () => void;
    let chain: Promise<unknown> = new Promise<void>((r) => (release = r)); // tab kia đang giữ khoá
    vi.stubGlobal("navigator", {
      ...navigator,
      locks: {
        request: (_name: string, cb: () => Promise<unknown>) => {
          const p = chain.then(cb);
          chain = p.catch(() => undefined);
          return p;
        },
      },
    });
    configureHttp({
      baseURL: "http://t/api",
      adapter: adapter((cfg) => {
        if (isRefresh(cfg)) {
          sent.push((JSON.parse(String(cfg.data)) as { refresh_token: string }).refresh_token);
          return ok({ access_token: "mine", refresh_token: "r3" });
        }
        return cfg.headers.Authorization === "Bearer mine" ? ok("done") : fail(401, 1004);
      }),
    });
    const pending = http.get("x");
    await new Promise((r) => setTimeout(r, 0));
    localStorage.setItem("bw_refresh_token", "r2"); // tab kia vừa xoay r1 → r2 rồi nhả khoá
    release();
    expect(await pending).toBe("done");
    expect(sent).toEqual(["r2"]); // không gửi lại r1 đã bị xoay (BE sẽ thu hồi cả họ)
    expect(getRefreshToken()).toBe("r3");
  });

  it("không có Web Locks, thua lượt (2104) → đọc lại refresh token tab kia vừa xoay, thử lại một lần, không đăng xuất", async () => {
    setTokens("old", "r1");
    const onAuthFailure = vi.fn();
    const sent: string[] = [];
    configureHttp({
      baseURL: "http://t/api",
      onAuthFailure,
      adapter: adapter((cfg) => {
        if (isRefresh(cfg)) {
          const rt = (JSON.parse(String(cfg.data)) as { refresh_token: string }).refresh_token;
          sent.push(rt);
          if (rt === "r1") {
            localStorage.setItem("bw_refresh_token", "r2"); // tab kia vừa xoay r1 → r2, BE báo 2104 cho lượt thua
            return fail(401, 2104);
          }
          return ok({ access_token: "a3", refresh_token: "r3" });
        }
        return cfg.headers.Authorization === "Bearer a3" ? ok("done") : fail(401, 1004);
      }),
    });
    expect(await http.get("x")).toBe("done");
    expect(sent).toEqual(["r1", "r2"]);
    expect(onAuthFailure).not.toHaveBeenCalled();
  });

  it("mở lại trang (chỉ còn refresh token): request đầu 401 → refresh một lần → gửi lại", async () => {
    localStorage.setItem("bw_refresh_token", "r1");
    let refreshes = 0;
    configureHttp({
      baseURL: "http://t/api",
      adapter: adapter((cfg) => {
        if (isRefresh(cfg)) return (refreshes++, ok({ access_token: "a1", refresh_token: "r2" }));
        return cfg.headers.Authorization === "Bearer a1" ? ok({ id: "u1" }) : fail(401, 1004);
      }),
    });
    expect(await http.get("auth/me")).toEqual({ id: "u1" });
    expect(refreshes).toBe(1);
  });

  it("đăng nhập sai (401) không kích refresh", async () => {
    setTokens("old", "r1");
    let refreshes = 0;
    configureHttp({
      baseURL: "http://t/api",
      adapter: adapter((cfg) => (isRefresh(cfg) ? (refreshes++, ok({ access_token: "x", refresh_token: "y" })) : fail(401, 2102))),
    });
    const err = await call("auth.login", { email: "a@b.c", password: "sai-mat-khau" }).catch((e: unknown) => e);
    expect(err).toMatchObject({ code: 2102 });
    expect(refreshes).toBe(0);
  });

  describe("mở lại trang (chỉ còn refresh token)", () => {
    it("3 request song song → refresh đúng một lần TRƯỚC request đầu, không ai ăn 401, cả ba mang Bearer mới", async () => {
      setTokens("", "r1");
      const log: string[] = [];
      const auths: (string | undefined)[] = [];
      configureHttp({
        baseURL: "http://t/api",
        adapter: adapter((cfg) => {
          if (isRefresh(cfg)) {
            log.push("refresh");
            return ok({ access_token: "fresh", refresh_token: "r2" });
          }
          log.push(`req:${cfg.url}`);
          auths.push(cfg.headers.Authorization as string | undefined);
          return cfg.headers.Authorization === "Bearer fresh" ? ok("done") : fail(401, 1004);
        }),
      });
      expect(await Promise.all([http.get("x"), http.get("y"), http.get("z")])).toEqual(["done", "done", "done"]);
      expect(log.filter((l) => l === "refresh")).toHaveLength(1);
      expect(log[0]).toBe("refresh");
      expect(log.filter((l) => l.startsWith("req:"))).toHaveLength(3);
      expect(auths).toEqual(["Bearer fresh", "Bearer fresh", "Bearer fresh"]);
    });

    it("refresh hỏng → xoá phiên, onAuthFailure đúng một lần, request bị reject ApiError 401", async () => {
      localStorage.setItem("bw_refresh_token", "gone");
      const onAuthFailure = vi.fn();
      let sent = 0;
      configureHttp({
        baseURL: "http://t/api",
        onAuthFailure,
        adapter: adapter((cfg) => {
          if (isRefresh(cfg)) return fail(401, 2104);
          sent++;
          return fail(401, 1004);
        }),
      });
      const err = await http.get("x").catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 401 });
      expect(onAuthFailure).toHaveBeenCalledTimes(1);
      expect(getRefreshToken()).toBeNull();
      expect(sent).toBe(0);
    });

    it("không có token nào → request đi không Authorization, không refresh", async () => {
      let refreshes = 0;
      const auths: unknown[] = [];
      configureHttp({
        baseURL: "http://t/api",
        adapter: adapter((cfg) => {
          if (isRefresh(cfg)) refreshes++;
          else auths.push(cfg.headers.Authorization);
          return ok("pub");
        }),
      });
      expect(await http.get("x")).toBe("pub");
      expect(refreshes).toBe(0);
      expect(auths).toEqual([undefined]);
    });

    it("auth.login khi chỉ có refresh token cũ → không refresh trước", async () => {
      localStorage.setItem("bw_refresh_token", "stale");
      let refreshes = 0;
      configureHttp({
        baseURL: "http://t/api",
        adapter: adapter((cfg) => {
          if (isRefresh(cfg)) refreshes++;
          return ok({ tokens: { access_token: "a", refresh_token: "b" } });
        }),
      });
      await http.post(endpoint("auth.login").path, { email: "a@b.c", password: "x" });
      expect(refreshes).toBe(0);
    });
  });
});

describe("call — một cửa theo bảng endpoints", () => {
  it("GET đưa input vào query; POST đưa input vào body JSON", async () => {
    const seen: { method?: string; url?: string; params?: unknown; data?: unknown }[] = [];
    configureHttp({
      baseURL: "http://t/api",
      adapter: adapter((cfg) => {
        seen.push({ method: cfg.method, url: cfg.url, params: cfg.params, data: cfg.data ? JSON.parse(String(cfg.data)) : undefined });
        return ok({ items: [], total: 0, limit: 20, offset: 0 });
      }),
    });
    await call("admin.list_users", { q: "an", limit: 20, offset: 0 });
    await call("admin.update_user", { user_id: "u2", is_active: false });
    expect(seen).toEqual([
      { method: "get", url: "admin/list_users", params: { q: "an", limit: 20, offset: 0 }, data: undefined },
      { method: "post", url: "admin/update_user", params: undefined, data: { user_id: "u2", is_active: false } },
    ]);
  });
});
