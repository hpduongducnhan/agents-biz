import type { SessionDetail } from "@/features/agent/api";
import { dotsOf, turnsOf } from "@/features/agent/trail";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { Badge, Markdown } from "@/ui";

import { RunDots } from "./RunDots";

export function UserBubble({ text, pending }: { text: string; pending?: boolean }) {
  return (
    <div
      className={cn("ml-auto max-w-[85%] whitespace-pre-wrap break-words rounded-3xl rounded-br-md px-4 py-2 text-sm text-primary-foreground", pending ? "bg-primary/80" : "bg-primary")}
      data-testid={pending ? "msg-pending" : "msg-user"}
    >
      {text}
    </div>
  );
}

export function ReplyBubble({ text }: { text: string }) {
  return <Markdown text={text} className="max-w-[92%] rounded-3xl rounded-bl-md bg-card px-4 py-2 shadow-sm" />;
}

type Content = { text?: string; status?: string };

type Props = { detail: SessionDetail; skipRun?: string | null; dim?: boolean };

/** Tin của một phiên theo lượt: tin user → hàng chấm (AI đã làm gì) → chữ trả lời. Không JSON, không tên chuyên gia.
 *  `skipRun`: lượt đang stream (phần trả lời đã lưu giữa chừng hiện ở khối live, không lặp). */
export function SessionTurns({ detail, skipRun, dim }: Props) {
  const t = useT();
  const titles = detail.tool_titles ?? {};
  const names = Object.fromEntries((detail.agents ?? []).filter((a) => a.kind === "specialist").map((a) => [a.id, a.name]));
  return (
    <div className={cn("grid gap-3", dim && "opacity-60")} data-testid={dim ? "session-previous" : "session-current"}>
      {turnsOf(detail.messages).map((turn) => {
        const replies = turn.replies.filter((m) => !skipRun || m.run_id !== skipRun);
        const texts = replies.filter((m) => m.role === "assistant" && (m.content as Content).text);
        const cancelled = replies.some((m) => (m.content as Content).status === "cancelled");
        return (
          <div key={turn.key} className="grid gap-1.5" data-testid="turn">
            {turn.user ? <UserBubble text={String((turn.user.content as Content).text ?? "")} /> : null}
            {replies.length ? <RunDots dots={dotsOf(replies, titles, names)} /> : null}
            {texts.map((m) => (
              <ReplyBubble key={m.id} text={String((m.content as Content).text)} />
            ))}
            {cancelled ? (
              <Badge variant="outline" className="w-fit">
                {t("chat.cancelled")}
              </Badge>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
