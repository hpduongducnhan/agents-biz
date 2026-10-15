import type { Span } from "@/features/agent/api";

export type SpanNode = { span: Span; children: SpanNode[] };

/** Cây span theo `parent_id` (thứ tự `seq`); span mồ côi (cha chưa ghi) treo ở gốc. */
export function buildTree(spans: Span[]): SpanNode[] {
  const nodes = new Map(spans.map((s) => [s.id, { span: s, children: [] as SpanNode[] }]));
  const roots: SpanNode[] = [];
  for (const s of [...spans].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))) {
    const node = nodes.get(s.id)!;
    const parent = s.parent_id ? nodes.get(s.parent_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

export function durationMs(s: { start?: string | null; end?: string | null }): number | null {
  if (!s.start || !s.end) return null;
  return Math.max(0, new Date(s.end).getTime() - new Date(s.start).getTime());
}

export const fmtMs = (ms: number | null) => (ms == null ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

export function tokensOf(s: Span): number | null {
  const u = "usage" in s ? (s.usage as Record<string, number> | undefined) : undefined;
  if (!u) return null;
  const n = (u.input ?? 0) + (u.output ?? 0);
  return n || null;
}
