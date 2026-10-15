/** Lượt đang stream của một phiên: nghe `agent:*` (một cửa realtime), hở `seq` / socket nối lại / mở phiên giữa lượt →
 *  bù bằng `agent.run_events`; lượt kết thúc → làm mới phiên + danh sách phiên. */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { useRealtime, useSocketStatus } from "@/lib/realtime/hooks";

import { agentApi, type SessionDetail } from "./api";
import { AGENT } from "./keys";
import { applyEvent, applyMany, isOpen, type LiveRun, newRun, type RunEvent, type RunEventName, withApprovals } from "./store";

function useRunEvents(onEvent: (ev: RunEvent) => void) {
  const on = (event: RunEventName) => (d: unknown) => onEvent({ event, data: d as RunEvent["data"] });
  useRealtime("agent:start", on("agent:start"));
  useRealtime("agent:route", on("agent:route"));
  useRealtime("agent:token", on("agent:token"));
  useRealtime("agent:step", on("agent:step"));
  useRealtime("agent:llm", on("agent:llm"));
  useRealtime("agent:approval", on("agent:approval"));
  useRealtime("agent:approval_decided", on("agent:approval_decided"));
  useRealtime("agent:end", on("agent:end"));
  useRealtime("agent:error", on("agent:error"));
}

export function useRunStream(sessionId: string | null, detail: SessionDetail | undefined, onError: (err: unknown) => void) {
  const qc = useQueryClient();
  const [live, setLiveState] = useState<LiveRun | null>(null);
  const ref = useRef<LiveRun | null>(null);
  const setLive = useCallback((run: LiveRun | null) => {
    ref.current = run;
    setLiveState(run);
  }, []);
  /** Sửa lượt đang mở theo bản mới nhất (sự kiện stream có thể tới trong lúc chờ một request). */
  const updateLive = useCallback(
    (fn: (run: LiveRun) => LiveRun) => {
      if (ref.current) setLive(fn(ref.current));
    },
    [setLive],
  );

  const finish = useCallback(
    async (sid: string) => {
      await qc.invalidateQueries({ queryKey: AGENT.session(sid) });
      await qc.invalidateQueries({ queryKey: AGENT.sessions() });
      setLive(null);
    },
    [qc, setLive],
  );

  const sync = useCallback(
    async (run: LiveRun) => {
      try {
        const got = await agentApi.runEvents(run.runId, run.lastSeq);
        const cur = ref.current;
        if (!cur || cur.runId !== run.runId) return;
        if (!got.available) {
          await finish(run.sessionId); // bộ đệm hết hạn → đọc lại phiên (nguồn sự thật)
          return;
        }
        const next = applyMany(cur, got.events as RunEvent[]);
        setLive(next);
        if (!isOpen(next)) await finish(next.sessionId);
      } catch (err) {
        onError(err);
      }
    },
    [finish, onError, setLive],
  );

  useRunEvents((ev) => {
    const cur = ref.current;
    if (!cur || ev.data.run_id !== cur.runId) return;
    const { run, gap } = applyEvent(cur, ev);
    if (gap) {
      void sync(cur);
      return;
    }
    setLive(run);
    if (!isOpen(run)) void finish(run.sessionId);
  });

  // Đổi phiên khi lượt khác đang chạy → bỏ phần hiển thị (lượt vẫn chạy; mở lại phiên sẽ bù từ bộ đệm).
  useEffect(() => {
    if (ref.current && ref.current.sessionId !== sessionId) setLive(null);
  }, [sessionId, setLive]);

  // Tải lại trang / mở phiên giữa lượt → dựng lại từ bộ đệm (+ thẻ duyệt từ API khi bộ đệm đã hết).
  const openRun = detail?.open_run;
  const approvals = detail?.approvals;
  useEffect(() => {
    if (openRun && sessionId && ref.current?.runId !== openRun.id) {
      const base = newRun(openRun.id, sessionId);
      const run = approvals?.length ? withApprovals(base, approvals) : base;
      setLive(run);
      void sync(run);
    }
  }, [openRun, approvals, sessionId, sync, setLive]);

  // Socket nối lại (có thể đã rơi sự kiện) → bù.
  const status = useSocketStatus();
  const prev = useRef(status);
  useEffect(() => {
    if (status === "connected" && prev.current !== "connected" && isOpen(ref.current)) void sync(ref.current!);
    prev.current = status;
  }, [status, sync]);

  const start = useCallback(
    (runId: string, sid: string) => {
      const run = newRun(runId, sid);
      setLive(run);
      void sync(run); // sự kiện tới trước khi biết run_id được bù ở đây
    },
    [setLive, sync],
  );

  return { live, setLive, updateLive, start };
}
