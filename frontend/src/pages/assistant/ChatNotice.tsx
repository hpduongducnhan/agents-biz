import { CircleAlert } from "lucide-react";
import { Link } from "react-router";

import type { SessionDetail } from "@/features/agent/api";
import type { ChatGuard } from "@/features/agent/useChatGuard";
import { ApiError } from "@/lib/api/errors";
import { useAuthStore } from "@/lib/auth/store";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";

export type Notice = { kind: "retry" | "tokenCap" | "notConfigured" | "busy" | "blocked"; at?: string } | null;

/** Lỗi gửi tin có cách xử lý riêng (chờ, hết hạn mức, chưa cấu hình, đang bận) → khung nhắc; lỗi khác → toast. */
export function noticeOf(err: unknown): Notice {
  if (!(err instanceof ApiError)) return null;
  const after = Number((err.data as { retry_after_sec?: number } | null)?.retry_after_sec ?? 0);
  const at = after ? new Date(Date.now() + after * 1000).toISOString() : undefined;
  if (err.code === 6001) return { kind: "retry", at };
  if (err.code === 6002) return { kind: "tokenCap", at };
  if (err.code === 6009 || err.code === 6010) return { kind: "notConfigured" };
  if (err.code === 6005) return { kind: "busy" };
  if (err.code === 6022) return { kind: "blocked" }; // nội dung chặn hiện ở `ChatLimitNotice` (theo `agent.chat_limits`)
  return null;
}

export function NoticeBox({ notice }: { notice: Notice }) {
  const t = useT();
  const sup = useAuthStore((s) => !!s.user?.is_superadmin);
  if (!notice || notice.kind === "blocked") return null;
  return (
    <div className="rounded-2xl border border-warning/50 bg-warning/10 px-3 py-2 text-sm" role="status" data-testid={`chat-notice-${notice.kind}`}>
      {notice.kind === "retry" && t("chat.retryIn", { time: notice.at ? fmt(notice.at, "relative") : "" })}
      {notice.kind === "tokenCap" && t("chat.tokenCap", { time: notice.at ? fmt(notice.at, "relative") : "" })}
      {notice.kind === "busy" && t("chat.busy")}
      {notice.kind === "notConfigured" && (
        <span className="flex flex-wrap items-center gap-2">
          {t("chat.notConfigured")}
          {sup ? (
            <Link to="/studio" className="font-semibold text-brand underline">
              {t("chat.openStudio")}
            </Link>
          ) : null}
        </span>
      )}
    </div>
  );
}

/** Lượt cuối của phiên hỏng (đã kết thúc) → dòng lỗi dưới tin cuối. */
export function RunFailed({ run }: { run: SessionDetail["last_run"] }) {
  const t = useT();
  if (run?.status !== "failed") return null;
  return (
    <p className="flex items-start gap-2 rounded-2xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert" data-testid="run-failed">
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
      {errorText(new ApiError({ message: run.error ?? t("chat.failed"), status: 500, code: run.error_code ?? null }))}
    </p>
  );
}

/** Đang bị chặn dùng trợ lý → khung báo tới khi nào + lý do; sắp hết hạn mức ngày → dòng nhỏ "còn N tin". */
export function ChatLimitNotice({ guard }: { guard: ChatGuard }) {
  const t = useT();
  const b = guard.blocked;
  if (b) {
    return (
      <div className="grid gap-1 rounded-2xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm" role="alert" data-testid="chat-blocked">
        <span className="font-semibold">{b.until ? t("chat.blocked", { time: fmt(b.until) }) : t("chat.blockedOpen")}</span>
        {b.reason ? <span>{t("chat.blockedReason", { reason: b.reason })}</span> : null}
      </div>
    );
  }
  if (guard.leftToday == null) return null;
  return (
    <p className="px-1 text-xs text-muted-foreground" data-testid="chat-left-today">
      {t("chat.leftToday", { n: guard.leftToday })}
    </p>
  );
}
