import { LoaderCircle } from "lucide-react";

import type { ApprovalState, LiveRun as Run, StepState } from "@/features/agent/store";
import { useT } from "@/lib/i18n";
import { Markdown } from "@/ui";

import { ApprovalList, type DecideFn } from "./ApprovalGroup";
import { ToolSteps } from "./ToolSteps";

type Props = { live: Run; deciding: boolean; onDecide: DecideFn };

/** Lượt đang chạy: dải "chuyển cho" (router), rồi mỗi chuyên gia một khối có nhãn — bước tool, thẻ duyệt, chữ chạy. */
export function LiveRunView({ live, deciding, onDecide }: Props) {
  const t = useT();
  const placed = new Set<string>();
  const take = <T extends { by?: { slug: string } }>(items: T[], slug: string | undefined, key: (x: T) => string) =>
    items.filter((x) => {
      if (x.by?.slug !== slug || placed.has(key(x))) return false;
      placed.add(key(x));
      return true;
    });
  const blocks = live.blocks.length ? live.blocks : [{ text: live.text }];
  const route = live.route?.steps ?? [];
  const waiting = live.approvals.some((a) => a.status === "pending");
  return (
    <div className="grid max-w-[92%] gap-3" data-testid="live-run" data-status={live.status}>
      {route.length > 1 ? (
        <p className="text-xs text-muted-foreground" data-testid="live-route">
          {t("chat.route", { steps: route.map((s) => s.name).join(" → ") })}
        </p>
      ) : null}
      {blocks.map((b, i) => {
        const steps = take<StepState>(live.steps, b.by?.slug, (x) => `s:${x.callId}`);
        const approvals = take<ApprovalState>(live.approvals, b.by?.slug, (x) => `a:${x.approvalId}`);
        return (
          <div key={`${b.by?.slug ?? "-"}-${i}`} className="grid gap-2" data-testid={`live-block-${b.by?.slug ?? "main"}`}>
            {b.by ? <span className="text-xs font-semibold text-brand">{b.by.name}</span> : null}
            <ToolSteps steps={steps} />
            <ApprovalList approvals={approvals} busy={deciding} onDecide={onDecide} />
            {b.text ? <Markdown text={b.text} className="rounded-3xl rounded-bl-md bg-card px-4 py-2 shadow-sm" /> : null}
          </div>
        );
      })}
      {live.status === "running" && !live.text && !waiting && (
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
          {t("chat.thinking")}
        </span>
      )}
    </div>
  );
}
