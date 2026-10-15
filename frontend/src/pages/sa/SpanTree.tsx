import { Anchor, Bot, ChevronRight, GitBranch, MessageSquare, ShieldCheck, UserRound, Wrench } from "lucide-react";

import type { Span } from "@/features/agent/api";
import { cn } from "@/lib/cn";

import { durationMs, fmtMs, type SpanNode, tokensOf } from "./traceUtil";

const ICON = { run: Bot, router: GitBranch, agent: UserRound, llm: MessageSquare, tool: Wrench, approval: ShieldCheck, hook: Anchor } as const;
const TONE: Record<string, string> = { ok: "text-positive", error: "text-destructive", waiting: "text-warning", running: "text-brand", cancelled: "text-muted-foreground" };

function Node({ node, depth, selected, onSelect, open, toggle }: { node: SpanNode; depth: number; selected: string | null; onSelect: (s: Span) => void; open: Set<string>; toggle: (id: string) => void }) {
  const s = node.span;
  const Icon = ICON[s.kind as keyof typeof ICON] ?? Bot;
  const expanded = open.has(s.id);
  const tokens = tokensOf(s);
  return (
    <li>
      <div className={cn("flex min-h-11 items-center gap-1 rounded-xl pr-2 text-sm md:min-h-9", selected === s.id ? "bg-brand-muted" : "hover:bg-accent")} style={{ paddingLeft: depth * 16 }}>
        <button
          type="button"
          aria-label={expanded ? "collapse" : "expand"}
          aria-expanded={expanded}
          className={cn("grid h-8 w-8 shrink-0 place-items-center", !node.children.length && "invisible")}
          onClick={() => toggle(s.id)}
          data-testid={`span-toggle-${s.id}`}
        >
          <ChevronRight className={cn("h-4 w-4 transition-transform", expanded && "rotate-90")} />
        </button>
        <button type="button" className="flex min-w-0 flex-1 items-center gap-2 py-1 text-left" onClick={() => onSelect(s)} data-testid={`span-${s.kind}-${s.id}`}>
          <Icon className={cn("h-4 w-4 shrink-0", TONE[s.status ?? ""] ?? "")} />
          <span className="min-w-0 flex-1 truncate">{s.name}</span>
          {tokens ? <span className="shrink-0 text-xs text-muted-foreground">{tokens} tok</span> : null}
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{fmtMs(durationMs(s))}</span>
        </button>
      </div>
      {expanded && node.children.length ? (
        <ul>
          {node.children.map((c) => (
            <Node key={c.span.id} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} open={open} toggle={toggle} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** Cây span mở / gập (mặc định mở hết mức đầu). */
export function SpanTree({ roots, selected, onSelect, open, setOpen }: { roots: SpanNode[]; selected: string | null; onSelect: (s: Span) => void; open: Set<string>; setOpen: (s: Set<string>) => void }) {
  const toggle = (id: string) => {
    const next = new Set(open);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setOpen(next);
  };
  return (
    <ul className="grid gap-0.5" data-testid="span-tree">
      {roots.map((n) => (
        <Node key={n.span.id} node={n} depth={0} selected={selected} onSelect={onSelect} open={open} toggle={toggle} />
      ))}
    </ul>
  );
}

