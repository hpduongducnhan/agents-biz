import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { type AgentCard, agentApi } from "@/features/agent/api";
import { AGENT } from "@/features/agent/keys";
import { isOpen } from "@/features/agent/store";
import { useChatGuard } from "@/features/agent/useChatGuard";
import { useDecide } from "@/features/agent/useDecide";
import { useRunStream } from "@/features/agent/useRunStream";
import { toastError } from "@/lib/query-client";
import { Skeleton } from "@/ui";

import { ChatLimitNotice, type Notice, NoticeBox, noticeOf, RunFailed } from "./ChatNotice";
import { Composer } from "./Composer";
import { LiveRunView } from "./LiveRun";
import { MessageBubble } from "./MessageBubble";
import { Starters } from "./Starters";

type Props = { agent: AgentCard; sessionId: string | null; onSession: (id: string) => void };

/** Khung chat một phiên: lịch sử + lượt đang stream (bước tool, thẻ duyệt, chữ chạy) + ô nhập / Dừng. */
export function ChatView({ agent, sessionId, onSession }: Props) {
  const qc = useQueryClient();
  const { data: detail, isLoading } = useQuery({
    queryKey: AGENT.session(sessionId ?? ""),
    queryFn: () => agentApi.session(sessionId!),
    enabled: !!sessionId,
  });
  const { live, updateLive, start } = useRunStream(sessionId, detail, toastError);
  const { deciding, decide } = useDecide(live?.runId, updateLive);
  const guard = useChatGuard();
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const all = detail?.messages ?? [];
  const messages = all.filter((m) => m.role !== "tool");
  const results = Object.fromEntries(
    all.filter((m) => m.role === "tool").map((m) => [String((m.content as { tool_call_id?: string }).tool_call_id), String((m.content as { text?: string }).text ?? "")]),
  );
  const entry = detail?.session.entry_agent_id;
  const names = Object.fromEntries((detail?.agents ?? []).filter((a) => a.kind === "specialist" && a.id !== entry).map((a) => [a.id, a.name]));

  const hasChat = !!(sessionId || pending || live);
  useEffect(() => {
    const el = scroller.current;
    if (el && hasChat) el.scrollTop = el.scrollHeight;
  }, [hasChat, messages.length, live?.text, live?.steps.length, live?.approvals.length, pending]);

  useEffect(() => {
    if (!live) setPending(null);
  }, [live]);

  const send = useCallback(
    async (content: string): Promise<boolean> => {
      setNotice(null);
      setPending(content);
      try {
        const out = await agentApi.send({ session_id: sessionId, agent_id: agent.id, content, client_msg_id: crypto.randomUUID() });
        start(out.run_id, out.session_id);
        if (out.session_id !== sessionId) onSession(out.session_id);
        await qc.invalidateQueries({ queryKey: AGENT.sessions() });
        return true;
      } catch (err) {
        setPending(null);
        const n = noticeOf(err);
        if (n) setNotice(n);
        else toastError(err);
        return false;
      }
    },
    [agent.id, onSession, qc, sessionId, start],
  );

  const stop = async () => {
    if (!live) return;
    try {
      await agentApi.cancel(live.runId);
    } catch (err) {
      toastError(err);
    }
  };

  const shownPending = pending && !messages.some((m) => m.role === "user" && m.run_id === live?.runId) ? pending : null;
  const empty = !sessionId && !shownPending && !live;
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="chat-view">
      <div ref={scroller} className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto overscroll-contain pb-4" aria-live="polite" data-testid="chat-scroll">
        {sessionId && isLoading ? <Skeleton className="h-24 w-full" /> : null}
        {empty ? <Starters starters={(agent.starters ?? []).map(String)} onPick={(s) => void send(s)} /> : null}
        {messages.map((m) => (
          <MessageBubble key={m.id} m={m} agentName={m.agent_id ? names[m.agent_id] : undefined} results={results} />
        ))}
        {shownPending ? (
          <div className="ml-auto max-w-[85%] whitespace-pre-wrap break-words rounded-3xl rounded-br-md bg-primary/80 px-4 py-2 text-sm text-primary-foreground" data-testid="msg-pending">
            {shownPending}
          </div>
        ) : null}
        {live && <LiveRunView live={live} deciding={deciding} onDecide={(ids, ok, r) => void decide(ids, ok, r)} />}
        {!live ? <RunFailed run={detail?.last_run ?? null} /> : null}
        <NoticeBox notice={notice} />
        <ChatLimitNotice guard={guard} />
      </div>
      <Composer running={isOpen(live)} disabled={!!guard.blocked} onSend={send} onStop={() => void stop()} />
    </section>
  );
}
