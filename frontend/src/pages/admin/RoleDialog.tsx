import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { type Permission, type Role, rbacApi } from "@/features/rbac/api";
import { RBAC } from "@/features/rbac/keys";
import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";
import { Field, FormDialog, Input, Label, Textarea } from "@/ui";

import { PermissionChecklist } from "./PermissionChecklist";

export type RoleDialogMode = { kind: "create" } | { kind: "edit" | "view"; role: Role };

export function RoleDialog({ mode, catalog, onClose }: { mode: RoleDialogMode; catalog: Permission[]; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const role = mode.kind === "create" ? null : mode.role;
  const readOnly = mode.kind === "view";
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [perms, setPerms] = useState<string[]>(role?.permissions ?? []);
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      role
        ? rbacApi.updateRole({ role_id: role.id, name: name.trim(), description, permissions: perms })
        : rbacApi.createRole({ name: name.trim(), description, permissions: perms }),
    onSuccess: () => {
      toast.success(t("roles.saved"));
      void qc.invalidateQueries({ queryKey: RBAC.all });
      onClose();
    },
    onError: (err) => setError(errorText(err)),
  });
  const title = mode.kind === "create" ? t("roles.create") : mode.kind === "edit" ? t("roles.edit") : t("roles.view");

  return (
    <FormDialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title={title}
      onSubmit={() => {
        if (!readOnly) save.mutate();
      }}
      submitting={save.isPending}
      disabled={readOnly || !name.trim()}
      error={error}
    >
      {readOnly && (
        <p data-testid="role-builtin-hint" className="rounded-xl bg-muted p-3 text-sm">
          {t("roles.builtinHint")}
        </p>
      )}
      <Field id="role-name" label={t("roles.name")}>
        <Input id="role-name" data-testid="role-name" value={name} disabled={readOnly} maxLength={64} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field id="role-desc" label={t("roles.description")}>
        <Textarea id="role-desc" data-testid="role-description" value={description} disabled={readOnly} rows={2} maxLength={500} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <div className="grid gap-1.5">
        <Label>{t("roles.permissions")}</Label>
        <PermissionChecklist catalog={catalog} value={perms} onChange={setPerms} readOnly={readOnly} />
      </div>
    </FormDialog>
  );
}
