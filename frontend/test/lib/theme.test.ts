import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");
const css = read("../../src/index.css");

/** Khối khai token: lấy mọi `--color-<tên>: #RRGGBB;` từ sau `opener` tới dấu `}` đầu tiên. */
function block(opener: string): Record<string, string> {
  const start = css.indexOf(opener);
  if (start < 0) throw new Error(`index.css thiếu khối ${opener}`);
  const body = css.slice(start + opener.length, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--color-([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1], (m[2] as string).toUpperCase()]));
}

function luminance(hex: string): number {
  const ch = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = ch.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

const light = block("@theme {");
const darkAuto = block(':root:not([data-theme="light"]) {');
const darkForced = block(':root[data-theme="dark"] {');

const PAIRS: [string, string][] = [
  ["foreground", "background"], ["card-foreground", "card"], ["popover-foreground", "popover"],
  ["primary-foreground", "primary"], ["secondary-foreground", "secondary"], ["muted-foreground", "background"],
  ["muted-foreground", "card"], ["muted-foreground", "muted"], ["accent-foreground", "accent"],
  ["destructive-foreground", "destructive"], ["destructive", "background"], ["brand-foreground", "brand"],
  ["brand", "background"], ["brand", "card"], ["brand", "brand-muted"], ["sidebar-foreground", "sidebar"],
  ["highlight-foreground", "highlight"], ["positive", "background"], ["positive", "card"], ["negative", "background"],
  ["warning", "background"], ["positive-foreground", "positive"], ["negative-foreground", "negative"],
  ["warning-foreground", "warning"],
  ["muted-foreground", "popover"], ["muted-foreground", "accent"], ["muted-foreground", "sidebar"],
  ["muted-foreground", "secondary"], ["brand", "sidebar"], ["brand", "accent"], ["brand", "popover"],
  ["negative", "card"], ["warning", "card"], ["destructive", "card"], ["foreground", "brand-muted"],
];

describe("theme — bảng màu thương hiệu", () => {
  it("token sáng lấy đúng 5 màu thương hiệu, và 5 màu có trong .claude/frontend/design/ui-system.md", () => {
    expect(light).toMatchObject({ brand: "#4F40DD", "brand-soft": "#A99FFF", highlight: "#F8B44A", background: "#FFF7ED", foreground: "#1C1745" });
    const readme = read("../../../.claude/frontend/design/ui-system.md").toUpperCase();
    for (const hex of ["#4F40DD", "#A99FFF", "#F8B44A", "#FFF7ED", "#1C1745"]) expect(readme).toContain(hex);
  });

  it("hai khối tối (theo hệ thống / ép) giống hệt nhau và đủ token như khối sáng", () => {
    expect(darkAuto).toEqual(darkForced);
    expect(Object.keys(darkAuto).sort()).toEqual(Object.keys(light).sort());
  });

  it.each([["sáng", light], ["tối", darkAuto]] as const)("mọi cặp chữ / nền ở theme %s đạt WCAG AA (≥ 4.5)", (_name, theme) => {
    const weak = PAIRS.map(([fg, bg]) => [fg, bg, contrast(theme[fg] as string, theme[bg] as string)] as const).filter(([, , r]) => r < 4.5);
    expect(weak).toEqual([]);
  });

  it("color-scheme: hai khối tối khai dark, :root khai light", () => {
    const body = (opener: string) => css.slice(css.indexOf(opener), css.indexOf("}", css.indexOf(opener)));
    expect(body(':root:not([data-theme="light"]) {')).toMatch(/color-scheme:\s*dark;/);
    expect(body(':root[data-theme="dark"] {')).toMatch(/color-scheme:\s*dark;/);
    expect(body(":root {")).toMatch(/color-scheme:\s*light;/);
  });

  it("theme tối: nút đặc là chữ trắng trên primary; brand là màu chữ, khác primary", () => {
    expect(darkAuto["primary-foreground"]).toBe("#FFFFFF");
    expect(contrast(darkAuto["primary-foreground"] as string, darkAuto.primary as string)).toBeGreaterThanOrEqual(4.5);
    expect(darkAuto.brand).not.toBe(darkAuto.primary);
  });

  it("index.html nạp Nunito, đặt theme trước khi vẽ; có mark tối cho nền tối", () => {
    const html = read("../../index.html");
    expect(html).toContain("family=Nunito");
    expect(html).toContain("bw-ui-v1");
    expect(existsSync(fileURLToPath(new URL("../../public/brand/mark-dark.svg", import.meta.url)))).toBe(true);
  });
});
