import { Check, CheckCheck, ChevronRight, ShieldAlert, X } from "lucide-react";
import { useState } from "react";

import type { ApprovalState } from "@/features/agent/store";
import { cn } from "@/lib/cn";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { Badge, Button, JsonView } from "@/ui";

import { ApprovalCard } from "./ApprovalCard";
import { ArgList, argSummary, RejectDialog, statusTone } from "./approvalParts";

export type DecideFn = (ids: string[], approve: boolean, reason: string | null) => void;
type Props = { approvals: ApprovalState[]; busy?: boolean; simple?: boolean; onDecide: DecideFn };

/** Yêu cầu duyệt của một khối: 1 cái → thẻ đầy đủ như cũ; ≥ 2 → thẻ gom có Duyệt / Từ chối tất cả. */
export function ApprovalList({ approvals, busy, simple, onDecide }: Props) {
  const [a, second] = approvals;
  if (!a) return null;
  if (!second) {
    return <ApprovalCard approval={a} busy={busy} simple={simple} onDecide={(ok, r) => onDecide([a.approvalId], ok, r)} />;
  }
  return <ApprovalGroup approvals={approvals} busy={busy} simple={simple} onDecide={onDecide} />;
}

function Item({ a, open, onToggle, busy, simple, onApprove, onReject }: { a: ApprovalState; open: boolean; onToggle: () => void; busy?: boolean; simple?: boolean; onApprove: () => void; onReject: () => void }) {
  const t = useT();
  const summary = argSummary(a.args);
  return (
    <li className="grid gap-1.5 p-2" data-testid={`approval-row-${a.approvalId}`}>
      <div className="flex min-w-0 items-center gap-1">
        <button type="button" className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-lg text-left md:min-h-9" aria-expanded={open} onClick={onToggle}>
          <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
          <span className="min-w-0">
            <span className="block truncate font-semibold">{a.title}</span>
            {summary ? <span className="block truncate text-xs text-muted-foreground">{summary}</span> : null}
          </span>
        </button>
        {a.status === "pending" ? (
          <span className="flex shrink-0 gap-1">
            <Button size="icon" variant="ghost" aria-label={t("approval.approve")} data-testid={`approve-${a.approvalId}`} disabled={busy} onClick={onApprove}>
              <Check className="h-4 w-4" />
            </Button>
            <Button size="icon" variant="ghost" aria-label={t("approval.reject")} data-testid={`reject-${a.approvalId}`} disabled={busy} onClick={onReject}>
              <X className="h-4 w-4" />
            </Button>
          </span>
        ) : (
          <Badge variant={statusTone(a.status)} className="shrink-0">
            {t(`approval.status.${a.status}`)}
          </Badge>
        )}
      </div>
      {open && (simple ? <ArgList args={a.args} /> : <JsonView value={a.args} maxHeight={220} />)}
      {a.reason ? (
        <p className="text-xs">
          {t("approval.reason")}: {a.reason}
        </p>
      ) : null}
    </li>
  );
}

/** Thẻ gom: đầu thẻ "N thao tác cần duyệt" + Duyệt / Từ chối tất cả (khi ≥ 2 cái còn chờ); mỗi yêu cầu một dòng gọn, bấm để
 *  xem tham số. Quyết hết → thu lại một dòng tóm tắt, bấm để mở lại. */
export function ApprovalGroup({ approvals, busy, simple, onDecide }: Props) {
  const t = useT();
  const [open, setOpen] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string[] | null>(null);
  const [showDone, setShowDone] = useState(false);
  const pending = approvals.filter((a) => a.status === "pending");
  const ids = pending.map((a) => a.approvalId);
  const soonest = pending.map((a) => a.expiresAt).filter(Boolean).sort()[0];
  const ok = approvals.filter((a) => a.status === "approved").length;
  const done = !pending.length;
  const rowsShown = !done || showDone;
  const title = done ? t("approval.summary", { ok, no: approvals.length - ok }) : t("approval.groupTitle", { n: pending.length });

  return (
    <div className="grid gap-2 rounded-2xl border border-warning/50 bg-warning/5 p-3 text-sm" data-testid="approval-group" data-pending={pending.length}>
      <button type="button" className="flex min-w-0 items-center gap-2 text-left" disabled={!done} aria-expanded={rowsShown} onClick={() => setShowDone((v) => !v)}>
        <ShieldAlert className="h-4 w-4 shrink-0 text-warning" />
        <span className="min-w-0 flex-1 font-semibold">{title}</span>
        {done ? <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", showDone && "rotate-90")} /> : null}
      </button>
      {pending.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" data-testid="approve-all" disabled={busy} onClick={() => onDecide(ids, true, null)}>
            <CheckCheck className="h-4 w-4" />
            {t("approval.approveAll", { n: ids.length })}
          </Button>
          <Button size="sm" variant="outline" data-testid="reject-all" disabled={busy} onClick={() => setRejecting(ids)}>
            {t("approval.rejectAll")}
          </Button>
          {soonest ? <span className="text-xs text-muted-foreground">{t("approval.expires", { at: fmt(soonest, "relative") })}</span> : null}
        </div>
      )}
      {rowsShown && (
        <ul className="grid divide-y divide-border rounded-xl border border-border bg-card">
          {approvals.map((a) => (
            <Item
              key={a.approvalId}
              a={a}
              open={open === a.approvalId}
              onToggle={() => setOpen(open === a.approvalId ? null : a.approvalId)}
              busy={busy}
              simple={simple}
              onApprove={() => onDecide([a.approvalId], true, null)}
              onReject={() => setRejecting([a.approvalId])}
            />
          ))}
        </ul>
      )}
      {rejecting && (
        <RejectDialog
          id={rejecting.length > 1 ? "all" : (rejecting[0] ?? "one")}
          title={rejecting.length > 1 ? t("approval.rejectAll") : undefined}
          onClose={() => setRejecting(null)}
          onSubmit={(reason) => {
            const list = rejecting;
            setRejecting(null);
            onDecide(list, false, reason);
          }}
        />
      )}
    </div>
  );
}
