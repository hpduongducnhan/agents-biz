// @vitest-environment jsdom
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { fmt, parseDate } from "@/lib/date";
import { registerDictionary, translate, useLocaleStore } from "@/lib/i18n";
import { DICTIONARIES, duplicateKeys } from "@/lib/i18n/register";

// jsdom: import.meta.url không phải file:// → lấy từ cwd (vitest chạy ở frontend/).
const SRC = join(process.cwd(), "src");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return sourceFiles(p);
    return /\.(ts|tsx)$/.test(name) ? [p] : [];
  });
}

const KEYS = new Set(DICTIONARIES.flatMap((d) => Object.keys(d)));
const params = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("i18n — parity vi / en", () => {
  it("mỗi key có đủ vi + en, không rỗng, không khai trùng giữa các file", () => {
    for (const dict of DICTIONARIES) {
      for (const [key, [vi, en]] of Object.entries(dict)) {
        expect(vi.trim(), key).not.toBe("");
        expect(en.trim(), key).not.toBe("");
        expect(params(vi), key).toEqual(params(en));
      }
    }
    expect(duplicateKeys()).toEqual([]);
  });

  it('mọi t("…") / translate("…") viết trong src đều có trong từ điển', () => {
    const missing: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(/\b(?:t|translate)\(\s*"([a-zA-Z][\w.-]*)"/g)) {
        if (!KEYS.has(m[1] as string)) missing.push(`${file.slice(SRC.length)}: ${m[1]}`);
      }
    }
    expect(missing).toEqual([]);
  });
});

describe("i18n — tra cứu", () => {
  it("nội suy tham số, theo ngôn ngữ đang chọn, thiếu key trả về key, ghi lang lên <html>", () => {
    registerDictionary("vi", { "t.hello": "Xin chào {name}" });
    registerDictionary("en", { "t.hello": "Hello {name}" });
    useLocaleStore.getState().setLocale("vi");
    expect(translate("t.hello", { name: "An" })).toBe("Xin chào An");
    useLocaleStore.getState().setLocale("en");
    expect(translate("t.hello", { name: "An" })).toBe("Hello An");
    expect(translate("t.missing")).toBe("t.missing");
    expect(translate("t.missing", "dự phòng")).toBe("dự phòng");
    expect(document.documentElement.lang).toBe("en");
    useLocaleStore.getState().setLocale("vi");
  });

  it("mã lỗi auth có thông điệp tiếng Việt", () => {
    expect(translate("err.2102")).toBe("Sai email hoặc mật khẩu");
    expect(translate("error.lookup", { cid: "abc" })).toBe("Mã tra cứu: abc");
  });
});

describe("ngày giờ", () => {
  it("chuỗi không có múi giờ hiểu là UTC; thời gian tương đối theo từ điển", () => {
    expect(parseDate("2026-10-12T01:02:03")?.toISOString()).toBe("2026-10-12T01:02:03.000Z");
    expect(parseDate("nope")).toBeNull();
    expect(fmt(null)).toBe("—");
    expect(fmt(new Date(Date.now() - 5 * 60_000).toISOString(), "relative")).toBe("5 phút trước");
  });
});
