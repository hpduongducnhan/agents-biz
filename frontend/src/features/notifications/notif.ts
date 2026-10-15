/** Tiêu đề thông báo theo ngôn ngữ đang chọn: key `notif.kind.<kind>` nội suy `params`; chưa khai key → `title` BE. */
import { call } from "@/lib/api";
import { ENDPOINTS, type OpName } from "@/lib/api/endpoints";
import type { TFn, TParams } from "@/lib/i18n";

type NotifLike = { kind: string; title: string; params?: Record<string, unknown> | null };

export function notifTitle(t: TFn, n: NotifLike): string {
  const params: TParams = {};
  for (const [k, v] of Object.entries(n.params ?? {})) if (typeof v === "string" || typeof v === "number") params[k] = v;
  const key = `notif.kind.${n.kind}`;
  const text = t(key, params);
  return text === key ? n.title : text;
}

/** Đường dẫn trong app của nút hành động (nếu có) — bỏ mọi giá trị không phải "/…". */
export function notifLink(n: { action?: unknown }): string | null {
  const to = (n.action as { to?: unknown } | null | undefined)?.to;
  return typeof to === "string" && to.startsWith("/") && !to.startsWith("//") ? to : null;
}

/** Link ngoài (https, mở tab mới) — vd file vừa xuất ra dịch vụ ngoài; bỏ mọi giá trị không phải https. */
export function notifUrl(n: { action?: unknown }): { url: string; label: string } | null {
  const a = n.action as { kind?: unknown; url?: unknown; label?: unknown } | null | undefined;
  if (a?.kind !== "url" || typeof a.url !== "string" || !a.url.startsWith("https://")) return null;
  return { url: a.url, label: typeof a.label === "string" && a.label ? a.label : "" };
}

export type NotifOperation = { operation: OpName; input: Record<string, unknown>; label: string };

/** Nút chạy một operation (vd "Ghi ngay" của định kỳ) — chỉ op có trong bảng `ENDPOINTS` (không chạy tên lạ). */
export function notifOperation(n: { action?: unknown }): NotifOperation | null {
  const a = n.action as { kind?: unknown; operation?: unknown; input?: unknown; label?: unknown } | null | undefined;
  if (a?.kind !== "operation" || typeof a.operation !== "string" || !(a.operation in ENDPOINTS)) return null;
  const input = a.input && typeof a.input === "object" ? (a.input as Record<string, unknown>) : {};
  return { operation: a.operation as OpName, input, label: typeof a.label === "string" ? a.label : "OK" };
}

/** Gọi op của thông báo (input do backend soạn, đã kiểm ở backend lúc chạy). */
export function runNotifOperation(op: NotifOperation): Promise<unknown> {
  return (call as (name: OpName, input: unknown) => Promise<unknown>)(op.operation, op.input);
}
