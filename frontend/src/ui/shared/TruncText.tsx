import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

import { Tooltip, TooltipContent, TooltipTrigger } from "../tooltip";

/** Chữ dài trong ô bảng (R16): cắt một dòng, hover / focus hiện đủ bằng Tooltip — không dùng thuộc tính title. */
export function TruncText({ text, className, mono, children }: { text: string; className?: string; mono?: boolean; children?: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className={cn("block truncate outline-none focus-visible:ring-2 focus-visible:ring-ring", mono && "font-mono text-xs", className)}>
          {children ?? text}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-[min(32rem,calc(100vw-2rem))] whitespace-pre-wrap break-words">{text}</TooltipContent>
    </Tooltip>
  );
}
