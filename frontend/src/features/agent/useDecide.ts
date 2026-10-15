import { useState } from "react";
import { toast } from "sonner";

import { translate } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";

import { agentApi } from "./api";
import type { ApprovalStatus, LiveRun } from "./store";

type Decided = { approval_id: string; status: string };

/** Quyết yêu cầu duyệt của lượt đang mở: 1 id → `agent.decide_approval`, ≥ 2 → `agent.decide_approvals`.
 *  Một lệnh một lúc — mọi nút duyệt của lượt khoá khi đang gửi. */
export function useDecide(runId: string | undefined, updateLive: (fn: (run: LiveRun) => LiveRun) => void) {
  const [deciding, setDeciding] = useState(false);
  const decide = async (ids: string[], approve: boolean, reason: string | null) => {
    if (!runId || deciding || !ids.length) return;
    setDeciding(true);
    try {
      let decided: Decided[];
      const [first] = ids;
      if (ids.length === 1 && first) {
        const out = await agentApi.decide(first, approve, reason);
        decided = [{ approval_id: out.approval_id, status: out.status }];
      } else {
        const out = await agentApi.decideMany(runId, ids, approve, reason);
        decided = out.decided;
        if (out.skipped.length) toast.info(translate("approval.skipped", { n: out.skipped.length }));
      }
      const status = new Map(decided.map((d) => [d.approval_id, d.status as ApprovalStatus]));
      updateLive((run) => ({
        ...run,
        approvals: run.approvals.map((a) => {
          const next = status.get(a.approvalId);
          return next ? { ...a, status: next, reason } : a;
        }),
      }));
    } catch (err) {
      toastError(err);
    } finally {
      setDeciding(false);
    }
  };
  return { deciding, decide };
}
