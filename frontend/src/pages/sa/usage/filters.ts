import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import type { UsageQuery } from "@/features/agent/api";
import { fmtNumber } from "@/lib/date";

export const RANGES = [1, 7, 30, 90] as const;
export type Range = (typeof RANGES)[number];
export const FILTER_KEYS = ["tenant_id", "user_id", "agent_id", "model_id", "provider_id", "credential_id", "purpose", "session_id"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export const GROUPS = ["provider", "model", "agent", "purpose", "tenant", "user", "key"] as const;
export type Group = (typeof GROUPS)[number];
export const METRICS = ["cost", "requests", "tokens", "errors"] as const;
export type Metric = (typeof METRICS)[number];

/** Dòng gộp theo chiều → bộ lọc tương ứng (bấm dòng = lọc sâu). */
export const FILTER_OF: Record<Group, FilterKey> = {
  provider: "provider_id",
  model: "model_id",
  agent: "agent_id",
  purpose: "purpose",
  tenant: "tenant_id",
  user: "user_id",
  key: "credential_id",
};

function startOf(range: Range): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - (range - 1));
  return d.toISOString();
}

/** Bộ lọc trang Usage nằm trên URL (`?range=&user_id=&by=&metric=…`) — chia sẻ / bấm sang từ trang khác được. */
export function useUsageFilters() {
  const [params, setParams] = useSearchParams();
  const raw = Number(params.get("range"));
  const range: Range = (RANGES as readonly number[]).includes(raw) ? (raw as Range) : 30;
  const by = (GROUPS as readonly string[]).includes(params.get("by") ?? "") ? (params.get("by") as Group) : "model";
  const metric = (METRICS as readonly string[]).includes(params.get("metric") ?? "") ? (params.get("metric") as Metric) : "cost";
  const filters = useMemo(() => {
    const out: Partial<Record<FilterKey, string>> = {};
    for (const k of FILTER_KEYS) {
      const v = params.get(k);
      if (v) out[k] = v;
    }
    return out;
  }, [params]);
  const since = useMemo(() => startOf(range), [range]);
  const query = useMemo(() => ({ since, ...filters }) as UsageQuery, [since, filters]);
  const set = useCallback(
    (patch: Record<string, string | null>) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v) next.set(k, v);
            else next.delete(k);
          }
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );
  const clear = useCallback(() => set(Object.fromEntries(FILTER_KEYS.map((k) => [k, null]))), [set]);
  return { range, by, metric, filters, since, query, set, clear };
}

export const usd = (v: number | string | null | undefined) => `$${Number(v ?? 0).toFixed(4)}`;

/** 1 234 · 12,3k · 4,5M — đủ đọc nhanh trên thẻ / bảng. */
export function compact(v: number | null | undefined): string {
  if (v == null) return "—";
  return fmtNumber(v, v >= 10_000 ? { notation: "compact", maximumFractionDigits: 1 } : undefined);
}

export function pct(part: number, whole: number): string {
  return whole > 0 ? fmtNumber((part * 100) / whole, { maximumFractionDigits: 1 }) : "0";
}
