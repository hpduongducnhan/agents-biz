import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { type AgentCard, agentApi } from "@/features/agent/api";
import { AGENT } from "@/features/agent/keys";
import { isOpen } from "@/features/agent/store";
import { useChatGuard } from "@/features/agent/useChatGuard";
import { useDecide } from "@/features/agent/useDecide";
import { useRunStream } from "@/features/agent/useRunStream";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Button, Skeleton } from "@/ui";

import { ChatLimitNotice, type Notice, NoticeBox, noticeOf, RunFailed } from "../ChatNotice";
import { Composer } from "../Composer";
import { Starters } from "../Starters";
import { LiveTurn } from "./LiveTurn";
import { SessionTurns, UserBubble } from "./Turns";

/** Phiên vừa gửi (server trả `session_id`) — giữ tới khi `agent.current_session` tải lại sau lúc gửi. */
type Sent = { id: string; at: number };

type Props = { agent: AgentCard; onActive: (id: string | null) => void };

/**
 * Màn chat đơn giản: không danh sách phiên — server chọn phiên đang mở (`auto`), quá hạn rảnh thì mở phiên
 * mới. Hiện phiên trước (mờ) + vạch "Cuộc trò chuyện mới" + phiên đang mở; mỗi lượt một hàng chấm + chữ trả lời.
 */
export function SimpleChat({ agent, onActive }: Props) {
  const t = useT();
  const qc = useQueryClient();
  const [fresh, setFresh] = useState(false);
  const currentKey = AGENT.sessions({ current: agent.id });
  const cur = useQuery({ queryKey: currentKey, queryFn: () => agentApi.current(agent.id), refetchInterval: 60_000 });
  const [sent, setSent] = useState<Sent | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const scroller = useRef<HTMLDivElement>(null);

  const server = cur.data?.current?.id ?? null;
  const stale = sent !== null && cur.dataUpdatedAt <= sent.at;
  const activeId = fresh ? (sent?.id ?? null) : sent && (stale || server === sent.id) ? sent.id : server;
  const prevId = [cur.data?.current?.id, cur.data?.previous?.id].find((id) => id && id !== activeId) ?? null;

  const active = useQuery({ queryKey: AGENT.session(activeId ?? ""), queryFn: () => agentApi.session(activeId!), enabled: !!activeId });
  const prev = useQuery({ queryKey: AGENT.session(prevId ?? ""), queryFn: () => agentApi.session(prevId!), enabled: !!prevId });
  const { live, updateLive, start } = useRunStream(activeId, active.data, toastError);
  const { deciding, decide } = useDecide(live?.runId, updateLive);
  const guard = useChatGuard();

  useEffect(() => onActive(activeId), [activeId, onActive]);
  useEffect(() => {
    if (!live) setPending(null);
  }, [live]);
  const count = (active.data?.messages.length ?? 0) + (prev.data?.messages.length ?? 0);
  const toBottom = useCallback(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);
  useEffect(toBottom, [toBottom, count, live?.text, live?.trail.length, live?.approvals.length, pending]);

  const send = useCallback(
    async (content: string): Promise<boolean> => {
      setNotice(null);
      setPending(content);
      const first = fresh && !sent;
      try {
        const out = await agentApi.send({ agent_id: agent.id, content, client_msg_id: crypto.randomUUID(), auto: !first });
        setSent({ id: out.session_id, at: Date.now() });
        setFresh(false);
        start(out.run_id, out.session_id);
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
    [agent.id, fresh, qc, sent, start],
  );

  // "Cuộc trò chuyện mới": bỏ phiên đang mở khỏi màn — tin tiếp theo gửi `auto: false` để mở phiên mới.
  const restart = () => {
    setSent(null);
    setFresh(true);
    setNotice(null);
  };

  const stop = async () => {
    if (!live) return;
    try {
      await agentApi.cancel(live.runId);
    } catch (err) {
      toastError(err);
    }
  };

  const messages = active.data?.messages ?? [];
  const shownPending = pending && !messages.some((m) => m.role === "user" && m.run_id === live?.runId) ? pending : null;
  const loading = cur.isLoading || (!!activeId && active.isLoading);
  const empty = !activeId && !shownPending && !live;
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="simple-chat">
      <div ref={scroller} className="grid min-h-0 flex-1 content-start gap-4 overflow-y-auto overscroll-contain pb-4" aria-live="polite" data-testid="chat-scroll">
        {loading ? <Skeleton className="h-24 w-full" /> : null}
        {prev.data ? <SessionTurns detail={prev.data} dim /> : null}
        {prevId && !loading ? <NewChatDivider /> : null}
        {empty && !prevId && !loading ? <Starters starters={(agent.starters ?? []).map(String)} onPick={(s) => void send(s)} /> : null}
        {active.data ? <SessionTurns detail={active.data} skipRun={live?.runId} /> : null}
        {shownPending ? <UserBubble text={shownPending} pending /> : null}
        {live ? <LiveTurn live={live} deciding={deciding} onDecide={(ids, ok, r) => void decide(ids, ok, r)} onGrow={toBottom} /> : null}
        {!live ? <RunFailed run={active.data?.last_run ?? null} /> : null}
        <NoticeBox notice={notice} />
        <ChatLimitNotice guard={guard} />
      </div>
      <Composer
        running={isOpen(live)}
        disabled={!!guard.blocked}
        onSend={send}
        onStop={() => void stop()}
        leading={
          <Button type="button" variant="ghost" size="icon" onClick={restart} disabled={isOpen(live) || (fresh && !sent)} aria-label={t("chat.newChat")} data-testid="chat-new">
            <MessageSquarePlus className="h-4 w-4" />
          </Button>
        }
      />
    </section>
  );
}

function NewChatDivider() {
  const t = useT();
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground" role="separator" data-testid="new-chat-divider">
      <span className="h-px flex-1 bg-border" />
      <span className="text-center">{t("chat.dividerNew")}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
