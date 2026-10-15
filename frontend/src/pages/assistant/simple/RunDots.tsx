import { type PointerEvent, useState } from "react";

import type { Dot } from "@/features/agent/trail";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui";

const COLOR: Record<Dot["status"], string> = {
  running: "bg-brand animate-pulse",
  ok: "bg-positive",
  error: "bg-destructive",
  waiting: "bg-warning animate-pulse",
};

const THINKING: Dot = { key: "thinking", kind: "thinking", status: "running" };

/** Nội dung tooltip của một chấm: AI đã làm gì (dòng 1), chi tiết (dòng 2), kết quả ổn / lỗi (dòng 3). */
function useDotText(d: Dot): { title: string; detail?: string; status: string } {
  const t = useT();
  const seconds = d.ms !== undefined ? t("chat.dot.seconds", { n: (d.ms / 1000).toFixed(1) }) : "";
  const by = d.by ? ` · ${d.by}` : "";
  const status = t(`chat.dot.status.${d.status}`);
  switch (d.kind) {
    case "route":
      return { title: t("chat.dot.route"), detail: d.items?.length ? t("chat.dot.routeTo", { to: d.items.join(" → ") }) : t("chat.dot.clarify"), status };
    case "llm": {
      const what = d.items?.length ? t("chat.dot.decided", { ops: d.items.join(", ") }) : t("chat.dot.compose");
      return { title: t("chat.dot.llm") + by, detail: [what, seconds].filter(Boolean).join(" · "), status };
    }
    case "tool":
      return { title: (d.name === "handoff" ? t("chat.dot.handoff") : (d.label ?? "")) + by, detail: d.detail, status };
    case "approval":
      return { title: t("chat.dot.approval", { op: d.label ?? "" }), detail: d.detail ? t(`approval.status.${d.detail}`) : undefined, status };
    case "error":
      return { title: t("chat.dot.error"), detail: d.label, status };
    default:
      return { title: t("chat.dot.thinking"), status };
  }
}

/** Một chấm: chuột hover mở tooltip; chạm (điện thoại) mở tooltip có kiểm soát, chạm chỗ khác thì đóng. */
function DotButton({ dot }: { dot: Dot }) {
  const [open, setOpen] = useState(false);
  const text = useDotText(dot);
  const label = [text.title, text.detail, text.status].filter(Boolean).join(" — ");
  const touch = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") e.preventDefault(); // Radix đóng tooltip khi nhấn — chạm thì giữ mở
  };
  return (
    <Tooltip open={open} onOpenChange={setOpen}>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          onPointerDown={touch}
          onClick={(e) => {
            e.preventDefault();
            setOpen(true);
          }}
          className="grid h-6 w-6 place-items-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          data-testid={`dot-${dot.kind}`}
          data-status={dot.status}
        >
          <span className={cn("h-2.5 w-2.5 rounded-full", COLOR[dot.status])} />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-72 text-xs" data-testid="dot-tip">
        <p className="font-semibold">{text.title}</p>
        {text.detail ? <p className="break-words text-muted-foreground">{text.detail}</p> : null}
        <p className={cn("font-semibold", dot.status === "ok" ? "text-positive" : dot.status === "error" ? "text-destructive" : "text-muted-foreground")}>{text.status}</p>
      </TooltipContent>
    </Tooltip>
  );
}

type Props = { dots: Dot[]; running?: boolean };

/** Hàng chấm tiến trình của một lượt — đang chạy mà không thao tác nào chạy thì thêm chấm "đang suy nghĩ". */
export function RunDots({ dots, running }: Props) {
  const t = useT();
  const busy = running && !dots.some((d) => d.status === "running" || d.status === "waiting");
  if (!dots.length && !running) return null;
  return (
    <TooltipProvider delayDuration={150}>
      <div className="-ml-1.5 flex flex-wrap items-center" data-testid="run-dots" data-running={running ? "1" : "0"}>
        {dots.map((d) => (
          <DotButton key={d.key} dot={d} />
        ))}
        {busy ? <DotButton dot={THINKING} /> : null}
        {running ? <span className="ml-1 text-xs text-muted-foreground">{t("chat.working")}</span> : null}
      </div>
    </TooltipProvider>
  );
}
