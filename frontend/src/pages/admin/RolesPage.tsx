import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Gauge, Lock, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { type Role, rbacApi } from "@/features/rbac/api";
import { RBAC } from "@/features/rbac/keys";
import { useIsSuperadmin } from "@/lib/auth/permissions";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { useIsDesktop } from "@/lib/use-media";
import { Badge, Button, Cell, ConfirmDialog, EmptyState, Row, Skeleton, Table, TruncText } from "@/ui";

import { RoleDialog, type RoleDialogMode } from "./RoleDialog";
import { RoleLimitsDialog } from "./RoleLimitsDialog";

export default function RolesPage() {
  const t = useT();
  const qc = useQueryClient();
  const desktop = useIsDesktop();
  const sup = useIsSuperadmin();
  const [limiting, setLimiting] = useState<Role | null>(null);
  const { data, isLoading } = useQuery({ queryKey: RBAC.roles(), queryFn: () => rbacApi.listRoles() });
  const { data: catalog = [] } = useQuery({ queryKey: RBAC.permissions(), queryFn: () => rbacApi.listPermissions(), staleTime: Infinity });
  const [mode, setMode] = useState<RoleDialogMode | null>(null);
  const [deleting, setDeleting] = useState<Role | null>(null);
  const remove = useMutation({
    mutationFn: (r: Role) => rbacApi.deleteRole(r.id),
    onSuccess: () => {
      toast.success(t("roles.deleted"));
      setDeleting(null);
      void qc.invalidateQueries({ queryKey: RBAC.all });
    },
    onError: (err) => {
      setDeleting(null);
      toastError(err);
    },
  });
  const roles = data?.items ?? [];

  const badge = (r: Role) =>
    r.is_builtin ? (
      <Badge variant="secondary" className="gap-1">
        <Lock className="h-3 w-3" />
        {t("roles.builtin")}
      </Badge>
    ) : null;
  const chatLimit = (r: Role) => r.policies.chat_per_day ?? t("roles.limitDefault");
  const limitsButton = (r: Role) =>
    sup ? (
      <Button size="icon" variant="ghost" aria-label={t("roles.limits")} data-testid={`role-limits-${r.name}`} onClick={() => setLimiting(r)}>
        <Gauge className="h-4 w-4" />
      </Button>
    ) : null;
  const roleActions = (r: Role) =>
    r.is_builtin || !sup ? (
      <Button size="sm" variant="ghost" data-testid={`role-view-${r.name}`} onClick={() => setMode({ kind: "view", role: r })}>
        <Eye className="h-4 w-4" />
        {t("common.view")}
      </Button>
    ) : (
      <div className="flex shrink-0 gap-1">
        <Button size="icon" variant="ghost" aria-label={t("common.edit")} data-testid={`role-edit-${r.name}`} onClick={() => setMode({ kind: "edit", role: r })}>
          <Pencil className="h-4 w-4" />
        </Button>
        <Button size="icon" variant="ghost" aria-label={t("common.delete")} data-testid={`role-delete-${r.name}`} onClick={() => setDeleting(r)}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    );
  const actions = (r: Role) => (
    <div className="flex shrink-0 items-center gap-1">
      {limitsButton(r)}
      {roleActions(r)}
    </div>
  );

  return (
    <div className="space-y-4">
      {sup && (
        <div className="flex justify-end">
          <Button data-testid="role-create" onClick={() => setMode({ kind: "create" })}>
            <Plus className="h-4 w-4" />
            {t("roles.create")}
          </Button>
        </div>
      )}
      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : roles.length === 0 ? (
        <EmptyState icon={<ShieldCheck className="h-10 w-10" />} title={t("roles.empty")} />
      ) : desktop ? (
        <Table head={[t("roles.name"), t("roles.description"), t("roles.permissions"), t("roles.chatLimit"), t("roles.users"), ""]}>
          {roles.map((r) => (
            <Row key={r.id} testId={`role-item-${r.name}`}>
              <Cell className="max-w-[240px]">
                <div className="flex min-w-0 items-center gap-2 font-semibold">
                  <TruncText text={r.name} className="min-w-0" />
                  {badge(r)}
                </div>
              </Cell>
              <Cell className="max-w-[360px] text-muted-foreground">
                <TruncText text={r.description || t("common.none")} />
              </Cell>
              <Cell className="num whitespace-nowrap">{t("roles.permCount", { n: r.permissions.length })}</Cell>
              <Cell className="num whitespace-nowrap">
                <span data-testid={`role-chat-limit-${r.name}`}>{chatLimit(r)}</span>
              </Cell>
              <Cell className="num">{r.user_count}</Cell>
              <Cell className="w-36 text-right">{actions(r)}</Cell>
            </Row>
          ))}
        </Table>
      ) : (
        <ul className="space-y-2">
          {roles.map((r) => (
            <li key={r.id} data-testid={`role-item-${r.name}`} className="flex min-w-0 items-start gap-3 rounded-2xl border border-border bg-card p-4 shadow-card">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex min-w-0 flex-wrap items-center gap-2 font-bold">
                  <span className="break-words">{r.name}</span>
                  {badge(r)}
                </div>
                {r.description ? <p className="break-words text-sm text-muted-foreground">{r.description}</p> : null}
                <p className="num text-xs text-muted-foreground">
                  {t("roles.permCount", { n: r.permissions.length })} · {t("roles.userCount", { n: r.user_count })} · {t("roles.chatLimit")}: {chatLimit(r)}
                </p>
              </div>
              {actions(r)}
            </li>
          ))}
        </ul>
      )}
      {mode && <RoleDialog mode={mode} catalog={catalog} onClose={() => setMode(null)} />}
      {limiting && <RoleLimitsDialog role={limiting} onClose={() => setLimiting(null)} />}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("common.delete")}
        description={t("roles.deleteConfirm", { name: deleting?.name ?? "" })}
        onConfirm={() => deleting && remove.mutate(deleting)}
        loading={remove.isPending}
      />
    </div>
  );
}
