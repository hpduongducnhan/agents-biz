import { ApiError } from "@/lib/api";
import { translate } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";

export type FormError = { text: string; cid: string | null };

/** Lỗi form kèm mã tra cứu — người dùng đọc được để báo lỗi (khớp log backend). */
export function formErrorOf(err: unknown): FormError {
  return { text: errorText(err), cid: err instanceof ApiError ? err.correlationId : null };
}

/** `next` chỉ nhận đường dẫn trong app (`/…`) — chặn `//host`, `/\host`, URL tuyệt đối. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

/** Thông báo đầu trang đăng nhập: bị khoá giữa phiên, hoặc lỗi Google trả về (`?error=<mã | google_*>`). */
export function bannerText(params: URLSearchParams): string | null {
  if (params.get("reason") === "disabled") return translate("auth.reason.disabled");
  const code = params.get("error");
  if (!code) return null;
  if (/^\d+$/.test(code)) {
    const key = `err.${code}`;
    const text = translate(key);
    if (text !== key) return text;
  }
  return translate("auth.err.google");
}
