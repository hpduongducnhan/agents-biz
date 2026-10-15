import { Check, ChevronsDownUp, ChevronsUpDown, Copy } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";

import { Button } from "../../button";
import { type ExpandCommand, JsonNode } from "./JsonNode";

type Parsed = { tree: true; data: unknown } | { tree: false; text: string };

/** Chuỗi là JSON object / mảng → cây; chuỗi khác (traceback, số dạng chữ…) → hiện nguyên chữ. */
export function parseJsonish(value: unknown): Parsed {
  if (typeof value !== "string") return { tree: true, data: value };
  try {
    const data: unknown = JSON.parse(value);
    return data !== null && typeof data === "object" ? { tree: true, data } : { tree: false, text: value };
  } catch {
    return { tree: false, text: value };
  }
}

type Props = { value: unknown; maxHeight?: number; defaultDepth?: number; className?: string };

/** JSON chỉ đọc (R17): cây thu / mở từng nút, mở / gấp tất cả, copy, maxHeight. */
export function JsonView({ value, maxHeight = 360, defaultDepth = 1, className }: Props) {
  const t = useT();
  const parsed = useMemo(() => parseJsonish(value), [value]);
  const [cmd, setCmd] = useState<ExpandCommand>(null);
  const [copied, setCopied] = useState(false);
  const text = parsed.tree ? JSON.stringify(parsed.data, null, 2) ?? String(parsed.data) : parsed.text;
  const expandable = parsed.tree && parsed.data !== null && typeof parsed.data === "object";
  const copy = () => {
    void navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className={cn("min-w-0 rounded-xl border border-border bg-muted/40", className)} data-testid="json-view">
      <div className="flex items-center justify-end gap-1 border-b border-border p-1">
        {expandable && (
          <>
            <Button type="button" variant="ghost" size="sm" aria-label={t("json.expandAll")} onClick={() => setCmd((c) => ({ open: true, n: (c?.n ?? 0) + 1 }))}>
              <ChevronsUpDown className="h-4 w-4" />
              <span className="hidden sm:inline">{t("json.expandAll")}</span>
            </Button>
            <Button type="button" variant="ghost" size="sm" aria-label={t("json.collapseAll")} onClick={() => setCmd((c) => ({ open: false, n: (c?.n ?? 0) + 1 }))}>
              <ChevronsDownUp className="h-4 w-4" />
              <span className="hidden sm:inline">{t("json.collapseAll")}</span>
            </Button>
          </>
        )}
        <Button type="button" variant="ghost" size="sm" aria-label={copied ? t("common.copied") : t("common.copy")} onClick={copy}>
          {copied ? <Check className="h-4 w-4 text-positive" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>
      <div data-testid="json-body" style={{ maxHeight }} className="overflow-auto p-3 font-mono text-xs leading-relaxed">
        {expandable ? (
          <JsonNode value={parsed.data} depth={0} defaultDepth={defaultDepth} cmd={cmd} />
        ) : (
          <pre className="whitespace-pre-wrap break-words">{text}</pre>
        )}
      </div>
    </div>
  );
}
