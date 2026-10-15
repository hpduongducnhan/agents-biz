import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import type { TraceQuery } from "@/features/agent/api";

export const KEYS = ["tenant_id", "user_id", "session_id", "agent_id", "status", "has_error", "model", "since", "until"] as const;
export type TraceKey = (typeof KEYS)[number];
export const STATUSES = ["running", "ok", "error", "waiting", "cancelled"] as const;

const dayStart = (d: string, plus = 0) => {
  const x = new Date(`${d}T00:00:00`);
  x.setDate(x.getDate() + plus);
  return x.toISOString();
};

/** Bộ lọc trang Trace trên URL — trang Usage bấm sang (`/sa/traces?user_id=…`) được. `since` / `until` là ngày
 *  (YYYY-MM-DD, `until` tính hết ngày). */
export function useTraceFilters() {
  const [params, setParams] = useSearchParams();
  const values = useMemo(() => {
    const out: Partial<Record<TraceKey, string>> = {};
    for (const k of KEYS) {
      const v = params.get(k);
      if (v) out[k] = v;
    }
    return out;
  }, [params]);
  const query = useMemo(() => {
    const { has_error, since, until, status, ...rest } = values;
    const q: Record<string, unknown> = { ...rest };
    if (status && (STATUSES as readonly string[]).includes(status)) q.status = status;
    if (has_error === "1") q.has_error = true;
    if (since) q.since = dayStart(since);
    if (until) q.until = dayStart(until, 1);
    return q as TraceQuery;
  }, [values]);
  const set = useCallback(
    (patch: Partial<Record<TraceKey, string | null>>) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v) next.set(k, v);
            else next.delete(k);
          }
          if (patch.user_id !== undefined && patch.session_id === undefined) next.delete("session_id");
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );
  const clear = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams]);
  return { values, query, set, clear };
}
