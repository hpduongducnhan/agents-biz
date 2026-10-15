// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BarChart } from "@/ui";

const bars = [
  { label: "01/10", tip: "2026-10-01", value: 0 },
  { label: "02/10", tip: "2026-10-02", value: 5 },
  { label: "03/10", tip: "2026-10-03", value: 10 },
];
const fmt = (v: number) => `${v}đ`;

describe("BarChart", () => {
  it("mặc định hiện giá trị lớn nhất; mỗi cột một vùng bấm; nhãn trục X là HTML", () => {
    render(<BarChart bars={bars} format={fmt} testId="c" />);
    expect(screen.getByTestId("c-value").textContent).toBe("max 10đ");
    expect(screen.getAllByTestId(/^c-bar-\d$/)).toHaveLength(3);
    expect(screen.getByText("02/10").tagName).toBe("SPAN");
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("3 cột");
  });

  it("rê chuột / bấm hiện giá trị cột; bấm giữ nguyên, bấm cột khác thì chuyển, rời chuột thì ẩn", () => {
    render(<BarChart bars={bars} format={fmt} testId="c" />);
    const value = screen.getByTestId("c-value");
    fireEvent.mouseEnter(screen.getByTestId("c-bar-1"));
    expect(value.textContent).toBe("2026-10-02: 5đ");
    fireEvent.click(screen.getByTestId("c-bar-1"));
    expect(value.textContent).toBe("2026-10-02: 5đ");
    fireEvent.click(screen.getByTestId("c-bar-2"));
    expect(value.textContent).toBe("2026-10-03: 10đ");
    fireEvent.mouseLeave(screen.getByTestId("c-bar-2"));
    expect(value.textContent).toBe("max 10đ");
  });

  it("không có tip thì dùng nhãn; mọi giá trị 0 → cột cao 0 và max 0", () => {
    const { container } = render(<BarChart bars={[{ label: "a", value: 0 }, { label: "b", value: 0 }]} format={fmt} testId="z" />);
    expect(screen.getByTestId("z-value").textContent).toBe("max 0đ");
    fireEvent.click(screen.getByTestId("z-bar-0"));
    expect(screen.getByTestId("z-value").textContent).toBe("a: 0đ");
    const heights = [...container.querySelectorAll("rect")].filter((r) => r.getAttribute("fill") !== "transparent").map((r) => r.getAttribute("height"));
    expect(heights).toEqual(["0", "0"]);
  });

  it("cột nhỏ nhưng > 0 vẫn thấy được (cao ≥ 1) và cột lớn nhất cao nhất; nhãn thưa dần khi nhiều cột", () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ label: `L${i}`, value: i === 0 ? 1 : i === 29 ? 10_000 : 0 }));
    const { container } = render(<BarChart bars={many} format={fmt} testId="m" />);
    const h = [...container.querySelectorAll("rect")].filter((r) => r.getAttribute("fill") !== "transparent").map((r) => Number(r.getAttribute("height")));
    expect(h[0]).toBeGreaterThanOrEqual(1);
    expect(h[29]).toBe(Math.max(...h));
    const labels = container.querySelectorAll("span.absolute");
    expect(labels.length).toBeLessThan(30);
    expect(labels.length).toBeGreaterThan(3);
  });

  it("không có cột nào → không lỗi", () => {
    render(<BarChart bars={[]} format={fmt} testId="e" />);
    expect(screen.getByTestId("e-value").textContent).toBe("max 0đ");
  });
});
