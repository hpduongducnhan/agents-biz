import { History, MessageSquarePlus } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import type { AgentCard } from "@/features/agent/api";
import { useT } from "@/lib/i18n";
import { Button, NativeSelect, Sheet } from "@/ui";

import { ChatView } from "./ChatView";
import { SessionList } from "./SessionList";

type Props = { agents: AgentCard[]; switcher?: ReactNode };

/** Màn gỡ lỗi (superadmin): danh sách phiên (sheet ở điện thoại, cột trái ở desktop), chọn agent, bước tool kèm
 *  tham số / kết quả. `?session=` `?agent=`. Cao đúng vùng nội dung: chỉ danh sách phiên và tin nhắn tự cuộn. */
export function DebugAssistant({ agents, switcher }: Props) {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const [sheet, setSheet] = useState(false);
  const sessionId = params.get("session");
  const agent = agents.find((a) => a.id === params.get("agent")) ?? agents[0]!;
  const select = (next: { session?: string | null; agent?: string | null }) => {
    const out = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) out.set(k, v);
      else out.delete(k);
    }
    setParams(out);
    setSheet(false);
  };
  const list = <SessionList sessionId={sessionId} onSelect={(id) => select({ session: id })} />;
  return (
    <div className="grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)] gap-3 md:grid-cols-[16rem_minmax(0,1fr)] md:gap-6" data-testid="assistant-page">
      <aside className="hidden min-h-0 md:flex md:flex-col">{list}</aside>
      <div className="flex min-h-0 min-w-0 flex-col gap-3">
        <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-2">
          {switcher}
          <Button variant="outline" size="sm" className="md:hidden" onClick={() => setSheet(true)} data-testid="chat-sessions">
            <History className="h-4 w-4" />
            {t("chat.sessions")}
          </Button>
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => select({ session: null })} aria-label={t("chat.newChat")}>
            <MessageSquarePlus className="h-4 w-4" />
          </Button>
          {agents.length > 1 ? (
            <NativeSelect
              aria-label={t("chat.agent")}
              className="ml-auto w-auto max-w-[50%]"
              value={agent.id}
              onChange={(e) => select({ agent: e.target.value, session: null })}
              data-testid="chat-agent"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </NativeSelect>
          ) : null}
        </div>
        <ChatView key={agent.id} agent={agent} sessionId={sessionId} onSession={(id) => select({ session: id })} />
      </div>
      <Sheet open={sheet} onOpenChange={setSheet} title={t("chat.sessions")} description={t("sub.assistant")} testId="chat-sessions-sheet">
        {list}
      </Sheet>
    </div>
  );
}
