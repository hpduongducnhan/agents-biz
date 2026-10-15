// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JsonView, parseJsonish, TooltipProvider } from "@/ui";

const sample = { operation: "admin.update_user", input: { user_id: "u2", roles: ["admin", "user"] }, ok: true, ms: 12, err: null };
const show = (value: unknown, maxHeight?: number) =>
  render(
    <TooltipProvider>
      <JsonView value={value} maxHeight={maxHeight} />
    </TooltipProvider>,
  );

describe("JsonView (R17)", () => {
  it("mặc định mở tầng đầu, gấp tầng sâu; bấm một nút để mở / gấp", () => {
    show(sample);
    expect(screen.getByText('"admin.update_user"')).toBeTruthy();
    expect(screen.queryByText('"u2"')).toBeNull();
    const node = screen.getByRole("button", { name: /"input"/ });
    expect(node.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(node);
    expect(screen.getByText('"u2"')).toBeTruthy();
  });

  it("mở tất cả / gấp tất cả", () => {
    show(sample);
    fireEvent.click(screen.getByRole("button", { name: "Mở tất cả" }));
    expect(screen.getByText('"admin"')).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Gấp tất cả" }));
    expect(screen.queryByText('"admin.update_user"')).toBeNull();
  });

  it("copy JSON đã định dạng; maxHeight áp vào khung cuộn", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    show(sample, 120);
    fireEvent.click(screen.getByRole("button", { name: "Sao chép" }));
    expect(writeText).toHaveBeenCalledWith(JSON.stringify(sample, null, 2));
    expect((screen.getByTestId("json-body") as HTMLElement).style.maxHeight).toBe("120px");
  });

  it("chuỗi JSON tự thành cây; chuỗi thường hiện nguyên chữ", () => {
    expect(parseJsonish('{"a":1}')).toEqual({ tree: true, data: { a: 1 } });
    expect(parseJsonish("Traceback (most recent call last)")).toEqual({ tree: false, text: "Traceback (most recent call last)" });
    expect(parseJsonish("42")).toEqual({ tree: false, text: "42" });
    show("lỗi: không phải JSON");
    expect(screen.getByText("lỗi: không phải JSON")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Mở tất cả" })).toBeNull();
  });
});
