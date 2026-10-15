import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Mail, Plus, UsersRound } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { type Invite, tenantApi } from "@/features/tenant/api";
import { TENANT } from "@/features/tenant/keys";
import { PERMS, useHasPermission } from "@/lib/auth/permissions";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Field, Input, Skeleton } from "@/ui";

import { InviteDialog } from "./InviteDialog";

function InviteRow({ inv, onRevoke }: { inv: Invite; onRevoke: (id: string) => void }) {
  const t = useT();
  return (
    <li data-testid={`invite-${inv.id}`} className="flex min-w-0 items-center gap-3 rounded-xl border border-border p-3">
      {inv.email ? <Mail className="h-4 w-4 shrink-0 text-muted-foreground" /> : <Link2 className="h-4 w-4 shrink-0 text-muted-foreground" />}
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold">{inv.email ?? t("invite.link")}</p>
        <p className="text-xs text-muted-foreground">
          {inv.role?.name ?? "member"} · {t("invite.uses", { uses: inv.uses, max: inv.max_uses })} · {t("invite.expires", { date: fmt(inv.expires_at, "date") })}
        </p>
      </div>
      <Button size="sm" variant="ghost" onClick={() => onRevoke(inv.id)} data-testid={`invite-revoke-${inv.id}`}>
        {t("invite.revoke")}
      </Button>
    </li>
  );
}

/** `/org` — tổ chức (tenant) của tôi: tên, số user / hạn mức, lời mời (D10–D12). */
export default function OrgPage() {
  const t = useT();
  const qc = useQueryClient();
  const canInvite = useHasPermission(PERMS.TENANT_INVITE);
  const canRename = useHasPermission(PERMS.TENANT_SETTINGS);
  const canSeeUsers = useHasPermission(PERMS.USER_VIEW);
  const [inviting, setInviting] = useState(false);
  const [name, setName] = useState<string | null>(null);
  const { data: tenant } = useQuery({ queryKey: TENANT.current(), queryFn: tenantApi.current });
  const { data: invites } = useQuery({ queryKey: TENANT.invites(), queryFn: tenantApi.invites, enabled: canInvite });
  const rename = useMutation({
    mutationFn: (v: string) => tenantApi.rename(v),
    onSuccess: (next) => {
      qc.setQueryData(TENANT.current(), next);
      setName(null);
      toast.success(t("org.saved"));
    },
    onError: (err) => toastError(err),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => tenantApi.revokeInvite(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TENANT.invites() });
      toast.success(t("invite.revoked"));
    },
    onError: (err) => toastError(err),
  });
  if (!tenant) return <Skeleton className="h-48 w-full" />;
  const draft = name ?? tenant.name;

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <Card className="shadow-card" data-testid="org-info">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2 text-base">
            {t("org.info")}
            <Badge variant={tenant.status === "active" ? "secondary" : "destructive"}>{t(`org.status.${tenant.status}`)}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (draft.trim() && draft !== tenant.name) rename.mutate(draft.trim());
            }}
          >
            <div className="min-w-0 flex-1">
              <Field id="org-name" label={t("org.name")}>
                <Input id="org-name" value={draft} maxLength={200} disabled={!canRename} onChange={(e) => setName(e.target.value)} data-testid="org-name" />
              </Field>
            </div>
            {canRename && (
              <Button type="submit" disabled={rename.isPending || !draft.trim() || draft === tenant.name} data-testid="org-rename">
                {t("org.rename")}
              </Button>
            )}
          </form>
          <div className="flex items-center justify-between gap-3 rounded-xl bg-muted/50 p-3 text-sm">
            <span className="flex items-center gap-2 font-semibold">
              <UsersRound className="h-4 w-4" /> {t("org.users")}
            </span>
            <span className="num" data-testid="org-user-count">
              {t("org.usersOf", { n: tenant.user_count, limit: tenant.user_limit || t("org.unlimited") })}
            </span>
          </div>
          {canSeeUsers && (
            <Link to="/admin/users" className="text-sm font-bold text-brand" data-testid="org-members">
              {t("org.members")}
            </Link>
          )}
        </CardContent>
      </Card>
      {canInvite && (
        <Card className="shadow-card" data-testid="org-invites">
          <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
            <CardTitle className="text-base">{t("invite.title")}</CardTitle>
            <Button size="sm" onClick={() => setInviting(true)} data-testid="invite-new">
              <Plus className="h-4 w-4" />
              {t("invite.new")}
            </Button>
          </CardHeader>
          <CardContent>
            {(invites ?? []).length === 0 ? (
              <EmptyState title={t("invite.empty")} className="py-8" />
            ) : (
              <ul className="grid gap-2">
                {(invites ?? []).map((inv) => (
                  <InviteRow key={inv.id} inv={inv} onRevoke={(id) => revoke.mutate(id)} />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
      <InviteDialog open={inviting} onOpenChange={setInviting} />
    </div>
  );
}
