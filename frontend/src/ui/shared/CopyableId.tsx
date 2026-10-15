import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";

import { Tooltip, TooltipContent, TooltipTrigger } from "../tooltip";

type Props = { value: string; short?: boolean; shortLen?: number; className?: string };

/** Hiện id / mã (rút gọn được) + copy nguyên giá trị; hover thấy đủ. */
export function CopyableId({ value, short = true, shortLen = 8, className }: Props) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const shown = short && value.length > shortLen ? `${value.slice(0, shortLen)}…` : value;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={copied ? t("common.copied") : t("common.copy")}
          onClick={() => {
            void navigator.clipboard?.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className={cn(
            "inline-flex min-h-9 items-center gap-1 rounded-md px-1 font-mono text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            className,
          )}
        >
          {shown}
          {copied ? <Check className="h-3 w-3 text-positive" /> : <Copy className="h-3 w-3" />}
        </button>
      </TooltipTrigger>
      <TooltipContent className="font-mono text-xs">{value}</TooltipContent>
    </Tooltip>
  );
}
