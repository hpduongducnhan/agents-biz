import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { adminApi, type AdminUser } from "@/features/admin/api";
import { ADMIN } from "@/features/admin/keys";
import { rbacApi } from "@/features/rbac/api";
import { RBAC } from "@/features/rbac/keys";
import { systemApi } from "@/features/system/api";
import { SYSTEM } from "@/features/system/keys";
import { useIsSuperadmin } from "@/lib/auth/permissions";
import { useAuthStore } from "@/lib/auth/store";
import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";
import { CheckList, FormDialog, Label, Switch } from "@/ui";

import { type LimitDraft, LimitFields, limitDefaults, limitDraft, limitPolicies, limitsChanged, limitsValid } from "./limitInput";

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

export function UserEditDialog({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const meId = useAuthStore((s) => s.user?.id);
  const { data: roles } = useQuery({ queryKey: RBAC.roles(), queryFn: () => rbacApi.listRoles() });
  // hạn mức ghi đè: chỉ superadmin, user đích không phải superadmin
  const canLimit = useIsSuperadmin() && !user.is_superadmin;
  const { data: pol } = useQuery({
    queryKey: ADMIN.userPolicies(user.id),
    queryFn: () => adminApi.userPolicies(user.id),
    enabled: canLimit,
  });
  const { data: settings } = useQuery({ queryKey: SYSTEM.settings(), queryFn: () => systemApi.getSettings(), enabled: canLimit });
  const original = user.roles.map((r) => r.id);
  const [active, setActive] = useState(user.is_active);
  const [roleIds, setRoleIds] = useState(original);
  const [touched, setTouched] = useState<LimitDraft | null>(null); // null = chưa chạm → theo giá trị đã lưu
  const [error, setError] = useState<string | null>(null);
  const self = meId === user.id;
  const draft = touched ?? limitDraft(pol?.policies);
  const limitsOk = limitsValid(draft);
  const limitChanged = canLimit && !!pol && limitsOk && limitsChanged(draft, pol.policies);
  const defaults = limitDefaults(settings);
  const accountChanged = active !== user.is_active || !sameSet(roleIds, original);
  const changed = accountChanged || limitChanged;

  const save = useMutation({
    mutationFn: async () => {
      if (accountChanged)
        await adminApi.updateUser({
          user_id: user.id,
          ...(active !== user.is_active ? { is_active: active } : {}),
          ...(sameSet(roleIds, original) ? {} : { role_ids: roleIds }),
        });
      if (limitChanged) await adminApi.setUserPolicies({ user_id: user.id, policies: limitPolicies(draft) });
    },
    onSuccess: () => {
      toast.success(t("admin.users.saved"));
      void qc.invalidateQueries({ queryKey: ADMIN.all });
      onClose();
    },
    onError: (err) => setError(errorText(err)),
  });

  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={t("admin.users.edit")} onSubmit={() => save.mutate()} submitting={save.isPending} disabled={!changed || !limitsOk} error={error}>
      <div className="min-w-0">
        <div className="truncate font-bold">{user.name}</div>
        <div className="break-all text-sm text-muted-foreground">{user.email}</div>
      </div>
      {user.is_superadmin && (
        <p data-testid="user-superadmin-hint" className="rounded-xl bg-brand-muted p-3 text-sm">
          {t("admin.users.superadminHint")}
        </p>
      )}
      <div className="flex items-center justify-between gap-4 rounded-xl border border-border p-3">
        <Label htmlFor="eu-active">{t("admin.users.active")}</Label>
        <Switch id="eu-active" data-testid="user-active" checked={active} onCheckedChange={setActive} disabled={self} />
      </div>
      {self && <p className="text-xs text-muted-foreground">{t("admin.users.selfHint")}</p>}
      <div className="grid gap-1.5">
        <Label>{t("admin.users.roles")}</Label>
        <div data-testid="user-roles" className="rounded-xl border border-border p-2">
          <CheckList
            items={(roles?.items ?? []).map((r) => ({ id: r.id, label: r.name, hint: r.description || undefined }))}
            value={roleIds}
            onChange={setRoleIds}
          />
        </div>
      </div>
      {canLimit && (
        <fieldset className="grid gap-3" data-testid="user-limits">
          <legend className="text-sm font-semibold">{t("admin.users.limits")}</legend>
          <LimitFields
            idPrefix="eu"
            testPrefix="user"
            draft={draft}
            defaults={defaults}
            disabled={!pol}
            onChange={setTouched}
          />
        </fieldset>
      )}
    </FormDialog>
  );
}
