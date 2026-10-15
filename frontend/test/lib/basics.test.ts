import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { apiUrl, socketPath, wsUrl } from "@/lib/api/url";
import { cn } from "@/lib/cn";
import { mkKeys } from "@/lib/keys";

describe("mkKeys", () => {
  it("gắn tiền tố miền cho mọi key — khớp `invalidates` của operation", () => {
    const k = mkKeys("admin", {
      users: (q: { q?: string }) => ["users", q],
      user: (id: string) => ["users", "detail", id],
    });
    expect(k.all).toEqual(["admin"]);
    expect(k.users({ q: "an" })).toEqual(["admin", "users", { q: "an" }]);
    expect(k.user("7")).toEqual(["admin", "users", "detail", "7"]);
  });
});

describe("cn", () => {
  it("gộp class, bỏ giá trị rỗng, class sau thắng class trùng nhóm", () => {
    expect(cn("h-9 px-2", undefined, "h-11")).toBe("px-2 h-11");
  });
});

describe("ApiError", () => {
  it("giữ status, code, correlation id, data", () => {
    const e = new ApiError({ message: "x", status: 409, code: 2101, correlationId: "c1", data: { a: 1 } });
    expect(e).toBeInstanceOf(Error);
    expect(e).toMatchObject({ name: "ApiError", status: 409, code: 2101, correlationId: "c1", data: { a: 1 } });
    expect(new ApiError({ message: "y", status: 0 })).toMatchObject({ code: null, correlationId: null });
  });
});

describe("apiUrl — một chỗ dựng URL (R15)", () => {
  it("ghép base với đường dẫn, bỏ / thừa", () => {
    expect(apiUrl("auth/login")).toBe("/bizwithagents/api/auth/login");
    expect(apiUrl("/health/live")).toBe("/bizwithagents/api/health/live");
    expect(apiUrl()).toBe("/bizwithagents/api");
    expect(wsUrl("health")).toBe("/bizwithagents/ws/health");
    expect(socketPath()).toBe("/bizwithagents/ws/socket.io/");
  });
});
