import { ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

/** Lệnh mở / gấp tất cả: `n` tăng mỗi lần bấm để nút con đồng bộ lại dù trạng thái giống lần trước. */
export type ExpandCommand = { open: boolean; n: number } | null;

type Props = { name?: string; index?: boolean; value: unknown; depth: number; defaultDepth: number; cmd: ExpandCommand };

function Primitive({ value }: { value: unknown }) {
  if (typeof value === "string") return <span className="break-all text-positive">{JSON.stringify(value)}</span>;
  if (typeof value === "number") return <span className="text-brand">{String(value)}</span>;
  return <span className="text-warning">{String(value)}</span>;
}

export function JsonNode({ name, index, value, depth, defaultDepth, cmd }: Props) {
  const [open, setOpen] = useState(depth < defaultDepth);
  useEffect(() => {
    if (cmd) setOpen(cmd.open);
  }, [cmd]);
  const label = name === undefined ? null : <span className="font-semibold text-foreground">{index ? name : JSON.stringify(name)}: </span>;
  if (value === null || typeof value !== "object") {
    return (
      <div className={cn(depth > 0 && "pl-4")}>
        {label}
        <Primitive value={value} />
      </div>
    );
  }
  const isArray = Array.isArray(value);
  const entries: [string, unknown][] = isArray
    ? value.map((v: unknown, i: number): [string, unknown] => [String(i), v])
    : Object.entries(value);
  const [l, r] = isArray ? (["[", "]"] as const) : (["{", "}"] as const);
  return (
    <div className={cn(depth > 0 && "pl-4")}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex max-w-full items-center gap-0.5 rounded text-left hover:bg-muted"
      >
        <ChevronRight aria-hidden className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-90")} />
        {label}
        <span>{l}</span>
        {!open && <span className="text-muted-foreground">{` … ${entries.length} ${r}`}</span>}
      </button>
      {open && (
        <>
          {entries.map(([k, v]) => (
            <JsonNode key={k} name={k} index={isArray} value={v} depth={depth + 1} defaultDepth={defaultDepth} cmd={cmd} />
          ))}
          <div>{r}</div>
        </>
      )}
    </div>
  );
}
