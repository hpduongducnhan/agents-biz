/** i18n tự viết (không lib): từ điển theo ngôn ngữ; mỗi file dict/<tên>.ts khai cặp [vi, en]. */
import { type Locale, useLocaleStore } from "./locale.store";

export type TParams = Record<string, string | number>;
export type TFn = (key: string, params?: TParams | string) => string;

const DICT: Record<Locale, Record<string, string>> = { vi: {}, en: {} };

export function registerDictionary(locale: Locale, dict: Record<string, string>): void {
  Object.assign(DICT[locale], dict);
  useLocaleStore.getState().bump();
}

function format(template: string, params?: TParams): string {
  return params ? template.replace(/\{(\w+)\}/g, (m, k: string) => (k in params ? String(params[k]) : m)) : template;
}

function lookup(locale: Locale, key: string, params?: TParams | string): string {
  const fallback = typeof params === "string" ? params : undefined;
  const found = DICT[locale][key] ?? DICT.vi[key] ?? fallback ?? key;
  return format(found, typeof params === "object" ? params : undefined);
}

/** Hook — re-render khi đổi ngôn ngữ hoặc nạp thêm dictionary. */
export function useT(): TFn {
  const locale = useLocaleStore((s) => s.locale);
  useLocaleStore((s) => s.version);
  return (key, params) => lookup(locale, key, params);
}

/** Bản không-hook cho toast / util ngoài React (đọc locale lúc gọi). */
export function translate(key: string, params?: TParams | string): string {
  return lookup(useLocaleStore.getState().locale, key, params);
}

export { type Locale, useLocaleStore };
