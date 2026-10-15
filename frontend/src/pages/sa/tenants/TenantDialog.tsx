import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { type Tenant, tenantsApi } from "@/features/tenant/api";
import { TENANTS } from "@/features/tenant/keys";
import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";
import { Field, FormDialog, Input, Label, Switch } from "@/ui";

const isLimit = (v: string) => v.trim() === "" || /^\d+$/.test(v.trim());

/** Tạo tổ chức (+ mời admin đầu tiên) hoặc sửa tên + chính sách (hạn mức user, cho dùng trợ lý). */
export function TenantDialog({ tenant, open, onOpenChange }: { tenant: Tenant | null; open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [name, setName] = useState(tenant?.name ?? "");
  const [adminEmail, setAdminEmail] = useState("");
  const [limit, setLimit] = useState(tenant?.policies.user_limit != null ? String(tenant.policies.user_limit) : "");
  const [agent, setAgent] = useState(tenant?.policies.agent_enabled !== false);
  const policies = { ...tenant?.policies, user_limit: limit.trim() === "" ? null : Number(limit), agent_enabled: agent ? null : false };
  const save = useMutation({
    mutationFn: async () => {
      if (tenant) return tenantsApi.update({ tenant_id: tenant.id, name: name.trim(), policies });
      const out = await tenantsApi.create({ name: name.trim(), admin_email: adminEmail.trim() || null, policies });
      return out.tenant;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TENANTS.all() });
      toast.success(t(tenant ? "tenants.saved" : "tenants.created"));
      onOpenChange(false);
    },
  });

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t(tenant ? "tenants.edit" : "tenants.create")}
      onSubmit={() => save.mutate()}
      submitting={save.isPending}
      disabled={!name.trim() || !isLimit(limit)}
      error={save.error ? errorText(save.error) : undefined}
    >
      <Field id="tn-name" label={t("tenants.name")}>
        <Input id="tn-name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} data-testid="tenant-name" />
      </Field>
      {!tenant && (
        <Field id="tn-admin" label={t("tenants.adminEmail")} hint={t("tenants.adminEmailHint")}>
          <Input id="tn-admin" type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} data-testid="tenant-admin-email" />
        </Field>
      )}
      <Field id="tn-limit" label={t("tenants.userLimit")} hint={t("tenants.userLimitHint")} error={isLimit(limit) ? undefined : t("sa.settings.invalid")}>
        <Input id="tn-limit" inputMode="numeric" className="num" value={limit} onChange={(e) => setLimit(e.target.value)} data-testid="tenant-user-limit" />
      </Field>
      <div className="flex items-center justify-between gap-4 rounded-xl border border-border p-3">
        <Label htmlFor="tn-agent">{t("tenants.agentEnabled")}</Label>
        <Switch id="tn-agent" checked={agent} onCheckedChange={setAgent} data-testid="tenant-agent-enabled" />
      </div>
    </FormDialog>
  );
}
