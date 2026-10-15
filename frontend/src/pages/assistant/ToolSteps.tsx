import { CircleAlert, CircleCheck, LoaderCircle } from "lucide-react";

import type { StepState } from "@/features/agent/store";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { JsonView } from "@/ui";

/** Một bước tool của lượt: gập mặc định (tên thao tác theo `title` op), mở xem tham số + kết quả; lỗi đỏ. */
export function StepCard({ step }: { step: StepState }) {
  const t = useT();
  const icon =
    step.status === "running" ? (
      <LoaderCircle className="h-4 w-4 animate-spin" />
    ) : step.status === "done" ? (
      <CircleCheck className="h-4 w-4 text-positive" />
    ) : (
      <CircleAlert className="h-4 w-4 text-destructive" />
    );
  return (
    <details
      className={cn("rounded-xl border px-3 py-2 text-xs", step.status === "error" ? "border-destructive/50 bg-destructive/5" : "border-border bg-muted/40")}
      data-testid={`step-${step.callId}`}
      data-status={step.status}
    >
      <summary className="flex min-h-11 cursor-pointer list-none flex-wrap items-center gap-2 md:min-h-0">
        {icon}
        <span className="font-semibold">{step.title}</span>
        <span className="text-muted-foreground">{t(`chat.step.${step.status}`)}</span>
      </summary>
      {step.args !== undefined && (
        <div className="mt-2 grid gap-1">
          <span className="font-semibold text-muted-foreground">{t("chat.step.args")}</span>
          <JsonView value={step.args} maxHeight={200} />
        </div>
      )}
      {step.preview ? (
        <div className="mt-2 grid gap-1">
          <span className="font-semibold text-muted-foreground">{t("chat.step.result")}</span>
          <JsonView value={step.preview} maxHeight={200} />
        </div>
      ) : null}
    </details>
  );
}

export function ToolSteps({ steps }: { steps: StepState[] }) {
  if (!steps.length) return null;
  return (
    <div className="grid gap-1.5" data-testid="tool-steps">
      {steps.map((s) => (
        <StepCard key={s.callId} step={s} />
      ))}
    </div>
  );
}
