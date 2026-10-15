import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { KeyRound, Pencil, Search, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { adminApi, type AdminUser } from "@/features/admin/api";
import { ADMIN } from "@/features/admin/keys";
import { PERMS, useHasPermission } from "@/lib/auth/permissions";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { useDebounced } from "@/lib/use-debounced";
import { useIsDesktop } from "@/lib/use-media";
import { Button, Cell, EmptyState, Input, Row, ServerPagination, Skeleton, Table, TruncText } from "@/ui";

import { ResetPasswordDialog } from "./ResetPasswordDialog";
import { UserBadges } from "./UserBadges";
import { UserEditDialog } from "./UserEditDialog";

const LIMIT = 20;

export default function UsersPage() {
  const t = useT();
  const desktop = useIsDesktop();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search.trim());
  const [offset, setOffset] = useState(0);
  const canManage = useHasPermission(PERMS.USER_MANAGE);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [resetting, setResetting] = useState<AdminUser | null>(null);
  useEffect(() => {
    setParams(q ? { q } : {}, { replace: true }); // q trong URL: deep link / back / chia sẻ đúng trang tìm
  }, [q, setParams]);
  const query = { ...(q ? { q } : {}), limit: LIMIT, offset };
  const { data, isLoading } = useQuery({ queryKey: ADMIN.users(query), queryFn: () => adminApi.listUsers(query), placeholderData: keepPreviousData });
  const items = data?.items ?? [];
  const roleNames = (u: AdminUser) => u.roles.map((r) => r.name).join(", ") || t("common.none");

  const actions = (u: AdminUser) =>
    canManage ? (
      <div className="flex shrink-0 gap-1">
        <Button size="icon" variant="ghost" aria-label={t("admin.users.edit")} data-testid={`user-edit-${u.id}`} onClick={() => setEditing(u)}>
          <Pencil className="h-4 w-4" />
        </Button>
        <Button size="icon" variant="ghost" aria-label={t("admin.users.reset")} data-testid={`user-reset-${u.id}`} onClick={() => setResetting(u)}>
          <KeyRound className="h-4 w-4" />
        </Button>
      </div>
    ) : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <div className="relative w-full md:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
            placeholder={t("admin.users.search")}
            aria-label={t("admin.users.search")}
            data-testid="users-search"
            className="pl-9"
          />
        </div>
      </div>
      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : items.length === 0 ? (
        <EmptyState icon={<Users className="h-10 w-10" />} title={t("admin.users.empty")} />
      ) : desktop ? (
        <Table head={[t("admin.users.col.name"), t("auth.field.email"), t("admin.users.roles"), t("admin.users.col.status"), t("admin.users.col.lastLogin"), ""]}>
          {items.map((u) => (
            <Row key={u.id} testId={`user-item-${u.id}`}>
              <Cell className="max-w-[200px] font-semibold">
                <TruncText text={u.name} />
              </Cell>
              <Cell className="max-w-[260px]">
                <TruncText text={u.email} />
              </Cell>
              <Cell className="max-w-[200px]">
                <TruncText text={roleNames(u)} />
              </Cell>
              <Cell>
                <UserBadges user={u} />
              </Cell>
              <Cell className="num whitespace-nowrap text-muted-foreground">{u.last_login_at ? fmt(u.last_login_at, "relative") : t("common.none")}</Cell>
              <Cell className="w-24">{actions(u)}</Cell>
            </Row>
          ))}
        </Table>
      ) : (
        <ul className="space-y-2">
          {items.map((u) => (
            <li key={u.id} data-testid={`user-item-${u.id}`} className="flex min-w-0 items-start gap-3 rounded-2xl border border-border bg-card p-4 shadow-card">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="truncate font-bold">{u.name}</div>
                <div className="break-all text-sm text-muted-foreground">{u.email}</div>
                <UserBadges user={u} />
                <div className="break-words text-xs text-muted-foreground">{roleNames(u)}</div>
              </div>
              {actions(u)}
            </li>
          ))}
        </ul>
      )}
      <ServerPagination offset={offset} limit={LIMIT} total={data?.total ?? 0} onChange={setOffset} />
      {editing && <UserEditDialog user={editing} onClose={() => setEditing(null)} />}
      {resetting && <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />}
    </div>
  );
}
