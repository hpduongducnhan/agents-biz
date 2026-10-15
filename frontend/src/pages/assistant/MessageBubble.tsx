import { Wrench } from "lucide-react";

import type { ChatMessage } from "@/features/agent/api";
import { useT } from "@/lib/i18n";
import { Badge, JsonView, Markdown } from "@/ui";

type Call = { id: string; name: string; args?: unknown };
type Content = { text?: string; tool_calls?: Call[]; status?: string };

/** Tên tool (`notifications_list`) → nhãn gọn khi không có `title` op (lịch sử chỉ lưu tên tool). */
export const toolLabel = (name: string) => name.replace(/_/g, " ");

type Props = { m: ChatMessage; agentName?: string; results?: Record<string, string> };

/** Một tin trong lịch sử phiên: tin người dùng (phải), tin trợ lý (nhãn chuyên gia, markdown, tool đã gọi — mở xem
 *  tham số + kết quả). Tin tool ẩn (kết quả ghép vào tool call qua `results`). */
export function MessageBubble({ m, agentName, results = {} }: Props) {
  const t = useT();
  const c = (m.content ?? {}) as Content;
  if (m.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] whitespace-pre-wrap break-words rounded-3xl rounded-br-md bg-primary px-4 py-2 text-sm text-primary-foreground" data-testid="msg-user">
        {c.text}
      </div>
    );
  }
  const calls = c.tool_calls ?? [];
  return (
    <div className="grid max-w-[92%] gap-1.5" data-testid="msg-assistant">
      {agentName ? (
        <span className="text-xs font-semibold text-brand" data-testid="msg-agent">
          {agentName}
        </span>
      ) : null}
      {calls.map((tc) => (
        <details key={tc.id} className="rounded-xl border border-border bg-muted/40 px-3 py-1.5 text-xs" data-testid={`call-${tc.id}`}>
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 text-muted-foreground md:min-h-0">
            <Wrench className="h-3 w-3" />
            {toolLabel(tc.name)}
          </summary>
          <div className="mt-2 grid gap-1">
            <span className="font-semibold text-muted-foreground">{t("chat.step.args")}</span>
            <JsonView value={tc.args ?? {}} maxHeight={200} />
            {results[tc.id] !== undefined ? (
              <>
                <span className="font-semibold text-muted-foreground">{t("chat.step.result")}</span>
                <JsonView value={results[tc.id]} maxHeight={200} />
              </>
            ) : null}
          </div>
        </details>
      ))}
      {c.text ? <Markdown text={c.text} className="rounded-3xl rounded-bl-md bg-card px-4 py-2 shadow-sm" /> : null}
      {c.status === "cancelled" && (
        <Badge variant="outline" className="w-fit">
          {t("chat.cancelled")}
        </Badge>
      )}
    </div>
  );
}
