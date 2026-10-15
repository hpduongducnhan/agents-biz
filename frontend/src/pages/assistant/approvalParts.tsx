import { useState } from "react";

import type { ApprovalStatus } from "@/features/agent/store";
import { useT } from "@/lib/i18n";
import { FormDialog, Label, Textarea } from "@/ui";

const HIDDEN = new Set(["idempotency_key"]);
const VALUE_LEN = 120;

const valueText = (v: unknown, max = VALUE_LEN) => {
  const text = typeof v === "string" ? v : JSON.stringify(v);
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
};

const argRows = (args: unknown): [string, unknown][] =>
  args && typeof args === "object" && !Array.isArray(args) ? Object.entries(args).filter(([k, v]) => !HIDDEN.has(k) && v !== null && v !== "") : [];

export const statusTone = (s: ApprovalStatus) => (s === "approved" ? "secondary" : s === "pending" ? "default" : "destructive");

/** Tóm tắt một dòng của tham số cho dòng thẻ gom: "khoá: giá trị · …". */
export const argSummary = (args: unknown) =>
  argRows(args)
    .map(([k, v]) => `${k}: ${valueText(v, 40)}`)
    .join(" · ");

/** Tham số dạng "khoá: giá trị" cho màn đơn giản (không JSON) — bỏ khoá nội bộ, giá trị lồng rút gọn một dòng. */
export function ArgList({ args }: { args: unknown }) {
  const rows = argRows(args);
  if (!rows.length) return null;
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs" data-testid="approval-args">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="break-words">{valueText(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Hộp thoại từ chối — lý do bắt buộc (trợ lý đọc lý do để biết vì sao). */
export function RejectDialog({ id, title, onClose, onSubmit }: { id: string; title?: string; onClose: () => void; onSubmit: (reason: string) => void }) {
  const t = useT();
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={title ?? t("approval.reject")}
      disabled={!reason.trim()}
      submitLabel={t("approval.reject")}
      onSubmit={() => {
        if (reason.trim()) onSubmit(reason.trim());
      }}
    >
      <div className="grid gap-1.5">
        <Label htmlFor={`reason-${id}`}>{t("approval.reason")}</Label>
        <Textarea
          id={`reason-${id}`}
          data-testid="reject-reason"
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          placeholder={t("approval.reasonRequired")}
        />
      </div>
    </FormDialog>
  );
}
