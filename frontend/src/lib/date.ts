/** Ngày giờ: BE trả UTC — chuỗi không có múi giờ phải hiểu là UTC (không thì lệch đúng offset máy). */
import { translate } from "@/lib/i18n";
import { useLocaleStore } from "@/lib/i18n/locale.store";

function intlTag(): string {
  return useLocaleStore.getState().locale === "en" ? "en-US" : "vi-VN";
}

export function parseDate(raw: string | null | undefined): Date | null {
  if (!raw) return null;
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(raw);
  const d = new Date(hasZone ? raw : `${raw}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmt(raw: string | null | undefined, style: "datetime" | "date" | "time" | "relative" = "datetime"): string {
  const d = parseDate(raw);
  if (!d) return "—";
  if (style === "relative") {
    // tương lai (hạn duyệt, lịch chạy) → "sau …"; lệch đồng hồ dưới 1 phút vẫn là "vừa xong"
    const diff = Date.now() - d.getTime();
    const ahead = diff < 0;
    const minutes = Math.floor(Math.abs(diff) / 60_000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    if (minutes < 1) return translate("time.justNow");
    if (minutes < 60) return translate(ahead ? "time.inMinutes" : "time.minutesAgo", { n: minutes });
    if (hours < 24) return translate(ahead ? "time.inHours" : "time.hoursAgo", { n: hours });
    if (days < 30) return translate(ahead ? "time.inDays" : "time.daysAgo", { n: days });
  }
  const opts: Intl.DateTimeFormatOptions = {};
  if (style !== "time") Object.assign(opts, { year: "numeric", month: "2-digit", day: "2-digit" });
  if (style === "time" || style === "datetime") Object.assign(opts, { hour: "2-digit", minute: "2-digit" });
  return new Intl.DateTimeFormat(intlTag(), opts).format(d);
}

export function fmtNumber(v: number | null | undefined, opts?: Intl.NumberFormatOptions): string {
  if (v == null || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat(intlTag(), opts).format(v);
}
