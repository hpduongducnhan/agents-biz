import { ShieldAlert } from "lucide-react";
import { useState } from "react";

import type { ApprovalState } from "@/features/agent/store";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { Badge, Button, JsonView } from "@/ui";

import { ArgList, RejectDialog, statusTone } from "./approvalParts";

type Props = { approval: ApprovalState; busy?: boolean; simple?: boolean; onDecide: (approve: boolean, reason: string | null) => void };

/** Thẻ duyệt một thao tác của trợ lý: thao tác + tham số (JsonView; màn đơn giản: danh sách khoá – giá trị) + Duyệt / Từ chối
 *  (bắt buộc lý do) + hạn. */
export function ApprovalCard({ approval: a, busy, simple, onDecide }: Props) {
  const t = useT();
  const [rejecting, setRejecting] = useState(false);
  return (
    <div className="grid gap-2 rounded-2xl border border-warning/50 bg-warning/5 p-3 text-sm" data-testid={`approval-${a.approvalId}`}>
      <div className="flex flex-wrap items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-warning" />
        <span className="font-semibold">{t("approval.title")}</span>
        <Badge variant={statusTone(a.status)}>{t(`approval.status.${a.status}`)}</Badge>
      </div>
      <p className="font-semibold">{a.title}</p>
      {simple ? <ArgList args={a.args} /> : <JsonView value={a.args} maxHeight={220} />}
      {a.reason ? (
        <p className="text-xs">
          {t("approval.reason")}: {a.reason}
        </p>
      ) : null}
      {a.status === "pending" && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => onDecide(true, null)} disabled={busy} data-testid={`approve-${a.approvalId}`}>
            {t("approval.approve")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setRejecting(true)} disabled={busy} data-testid={`reject-${a.approvalId}`}>
            {t("approval.reject")}
          </Button>
          {a.expiresAt ? <span className="text-xs text-muted-foreground">{t("approval.expires", { at: fmt(a.expiresAt, "relative") })}</span> : null}
        </div>
      )}
      {rejecting && (
        <RejectDialog
          id={a.approvalId}
          onClose={() => setRejecting(false)}
          onSubmit={(reason) => {
            setRejecting(false);
            onDecide(false, reason);
          }}
        />
      )}
    </div>
  );
}
