// @vitest-environment jsdom
import { MutationObserver } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { errorText, queryClient, toastError } from "@/lib/query-client";

import { toast } from "../sonner-mock";

vi.mock("sonner", () => import("../sonner-mock"));

const conflict = new ApiError({ message: "Email đã có", status: 409, code: 2101, correlationId: "c-1" });

describe("toastError", () => {
  it("mã lỗi có bản dịch → thông điệp tiếng Việt + Mã tra cứu", () => {
    toastError(conflict);
    expect(toast.error).toHaveBeenCalledWith("Email này đã được đăng ký", { description: "Mã tra cứu: c-1" });
  });

  it("mã lạ → thông điệp BE; mạng hỏng → câu riêng; lỗi không phải ApiError → câu chung", () => {
    expect(errorText(new ApiError({ message: "Lỗi lạ từ BE", status: 400, code: 9999 }))).toBe("Lỗi lạ từ BE");
    expect(errorText(new ApiError({ message: "Network error", status: 0 }))).toBe("Không kết nối được máy chủ");
    expect(errorText(new Error("x"))).toBe("Có lỗi xảy ra, vui lòng thử lại");
  });

  it("401 không toast (interceptor / guard lo)", () => {
    toastError(new ApiError({ message: "x", status: 401, code: 1004 }));
    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe("queryClient", () => {
  it("query lỗi → toast; meta.silent → im lặng", async () => {
    await queryClient.fetchQuery({ queryKey: ["t", 1], queryFn: () => Promise.reject(conflict), retry: false }).catch(() => undefined);
    expect(toast.error).toHaveBeenCalledTimes(1);
    await queryClient
      .fetchQuery({ queryKey: ["t", 2], queryFn: () => Promise.reject(conflict), retry: false, meta: { silent: true } })
      .catch(() => undefined);
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("mutation có onError riêng → không toast toàn cục", async () => {
    const own = vi.fn();
    const m = new MutationObserver(queryClient, { mutationFn: () => Promise.reject(conflict), onError: own });
    await m.mutate(undefined).catch(() => undefined);
    expect(own).toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("retry: lỗi 4xx không thử lại; 5xx thử tối đa 2 lần", () => {
    const retry = queryClient.getDefaultOptions().queries?.retry as (n: number, e: unknown) => boolean;
    expect(retry(0, new ApiError({ message: "x", status: 403 }))).toBe(false);
    expect(retry(0, new ApiError({ message: "x", status: 502 }))).toBe(true);
    expect(retry(2, new ApiError({ message: "x", status: 502 }))).toBe(false);
  });
});
