import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Pencil, Plus, Search } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { type Tenant, tenantsApi } from "@/features/tenant/api";
import { TENANTS } from "@/features/tenant/keys";
import { useIsDesktop } from "@/lib/use-media";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Badge, Button, Cell, ConfirmDialog, EmptyState, Input, Row, Skeleton, Table, TruncText } from "@/ui";

import { TenantDialog } from "./tenants/TenantDialog";

/** `/sa/tenants` — superadmin quản mọi tổ chức (D10–D12): tạo + mời admin, sửa hạn mức, khoá / mở. */
export default function TenantsPage() {
  const t = useT();
  const qc = useQueryClient();
  const desktop = useIsDesktop();
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Tenant | "new" | null>(null);
  const [suspending, setSuspending] = useState<Tenant | null>(null);
  const query = { q: q.trim() || null, limit: 100 };
  const { data, isLoading } = useQuery({ queryKey: TENANTS.all(query), queryFn: () => tenantsApi.list(query) });
  const toggle = useMutation({
    mutationFn: (x: Tenant) => (x.status === "active" ? tenantsApi.suspend(x.id) : tenantsApi.resume(x.id)),
    onSuccess: (x) => {
      void qc.invalidateQueries({ queryKey: TENANTS.all() });
      toast.success(t(x.status === "active" ? "tenants.resumed" : "tenants.suspended"));
      setSuspending(null);
    },
    onError: (err) => toastError(err),
  });
  const items = data?.items ?? [];
  const status = (x: Tenant) => <Badge variant={x.status === "active" ? "secondary" : "destructive"}>{t(`org.status.${x.status}`)}</Badge>;
  const actions = (x: Tenant) => (
    <div className="flex shrink-0 items-center gap-1">
      <Button size="icon" variant="ghost" aria-label={t("tenants.edit")} onClick={() => setEditing(x)} data-testid={`tenant-edit-${x.slug}`}>
        <Pencil className="h-4 w-4" />
      </Button>
      <Button size="sm" variant="ghost" onClick={() => (x.status === "active" ? setSuspending(x) : toggle.mutate(x))} data-testid={`tenant-toggle-${x.slug}`}>
        {t(x.status === "active" ? "tenants.suspend" : "tenants.resume")}
      </Button>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <div className="relative w-full md:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" aria-label={t("tenants.search")} placeholder={t("tenants.search")} value={q} onChange={(e) => setQ(e.target.value)} data-testid="tenants-search" />
        </div>
        <Button onClick={() => setEditing("new")} data-testid="tenant-create">
          <Plus className="h-4 w-4" />
          {t("tenants.create")}
        </Button>
      </div>
      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : items.length === 0 ? (
        <EmptyState icon={<Building2 className="h-10 w-10" />} title={t("tenants.empty")} />
      ) : desktop ? (
        <Table head={[t("tenants.name"), "slug", t("tenants.users"), t("tenants.status"), ""]}>
          {items.map((x) => (
            <Row key={x.id} testId={`tenant-${x.slug}`}>
              <Cell className="max-w-[260px] font-semibold">
                <TruncText text={x.name} />
              </Cell>
              <Cell className="max-w-[200px] text-muted-foreground">
                <TruncText text={x.slug} />
              </Cell>
              <Cell className="num whitespace-nowrap">{t("org.usersOf", { n: x.user_count, limit: x.user_limit || t("org.unlimited") })}</Cell>
              <Cell>{status(x)}</Cell>
              <Cell className="w-48 text-right">{actions(x)}</Cell>
            </Row>
          ))}
        </Table>
      ) : (
        <ul className="space-y-2">
          {items.map((x) => (
            <li key={x.id} data-testid={`tenant-${x.slug}`} className="flex min-w-0 items-start gap-3 rounded-2xl border border-border bg-card p-4 shadow-card">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex min-w-0 flex-wrap items-center gap-2 font-bold">
                  <span className="break-words">{x.name}</span>
                  {status(x)}
                </div>
                <p className="num text-xs text-muted-foreground">
                  {x.slug} · {t("org.usersOf", { n: x.user_count, limit: x.user_limit || t("org.unlimited") })}
                </p>
              </div>
              {actions(x)}
            </li>
          ))}
        </ul>
      )}
      {editing && <TenantDialog key={editing === "new" ? "new" : editing.id} tenant={editing === "new" ? null : editing} open onOpenChange={(v) => !v && setEditing(null)} />}
      <ConfirmDialog
        open={!!suspending}
        onOpenChange={(v) => !v && setSuspending(null)}
        title={t("tenants.suspend")}
        description={suspending ? t("tenants.suspendConfirm", { name: suspending.name }) : ""}
        confirmLabel={t("tenants.suspend")}
        loading={toggle.isPending}
        onConfirm={() => suspending && toggle.mutate(suspending)}
      />
    </div>
  );
}
