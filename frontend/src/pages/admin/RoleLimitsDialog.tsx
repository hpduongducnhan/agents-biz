import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { type Role, rbacApi } from "@/features/rbac/api";
import { RBAC } from "@/features/rbac/keys";
import { systemApi } from "@/features/system/api";
import { SYSTEM } from "@/features/system/keys";
import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";
import { FormDialog } from "@/ui";

import { type LimitDraft, LimitFields, limitDefaults, limitDraft, limitPolicies, limitsChanged, limitsValid } from "./limitInput";

/** Superadmin đặt hạn mức cho role — kể cả role có sẵn: tin chat / phút · giờ · ngày. */
export function RoleLimitsDialog({ role, onClose }: { role: Role; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const { data: settings } = useQuery({ queryKey: SYSTEM.settings(), queryFn: () => systemApi.getSettings() });
  const [draft, setDraft] = useState<LimitDraft>(() => limitDraft(role.policies));
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => rbacApi.setRolePolicies({ role_id: role.id, policies: limitPolicies(draft) }),
    onSuccess: () => {
      toast.success(t("roles.limitsSaved"));
      void qc.invalidateQueries({ queryKey: RBAC.all });
      onClose();
    },
    onError: (err) => setError(errorText(err)),
  });
  const defaults = limitDefaults(settings);

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t("roles.limitsTitle", { name: role.name })}
      onSubmit={() => save.mutate()}
      submitting={save.isPending}
      disabled={!limitsValid(draft) || !limitsChanged(draft, role.policies)}
      error={error}
    >
      <p className="text-sm text-muted-foreground">{t("roles.limitsHint")}</p>
      <LimitFields idPrefix="rl" testPrefix="role" draft={draft} defaults={defaults} onChange={setDraft} />
    </FormDialog>
  );
}
