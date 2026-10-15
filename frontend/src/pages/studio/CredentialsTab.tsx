import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { type Credential, credentialsApi, studioApi } from "@/features/agent/api";
import { CREDENTIALS, STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Button, ConfirmDialog, EmptyState, Skeleton } from "@/ui";

import { CredentialDialog } from "./CredentialDialog";
import { ItemCard, StatusBadge, TabActions, useStudioMutation } from "./common";

const LIST = { limit: 100 };

/** API key mã hoá: danh sách chỉ hiện `masked_hint` — giá trị không bao giờ quay lại trình duyệt. */
export function CredentialsTab() {
  const t = useT();
  const { data, isLoading } = useQuery({ queryKey: CREDENTIALS.list(LIST), queryFn: () => credentialsApi.list(LIST) });
  const providers = useQuery({ queryKey: STUDIO.providers(), queryFn: studioApi.providers });
  const [editing, setEditing] = useState<Credential | "new" | null>(null);
  const [deleting, setDeleting] = useState<Credential | null>(null);
  const remove = useStudioMutation((id: string) => credentialsApi.remove(id), [CREDENTIALS.all, STUDIO.agents()], () => setDeleting(null));
  const providerName = (id: string | null | undefined) => providers.data?.find((p) => p.id === id)?.name ?? t("studio.noProvider");
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  const items = data?.items ?? [];
  return (
    <div className="grid gap-3">
      <TabActions>
        <Button onClick={() => setEditing("new")} data-testid="credential-add">
          <Plus className="h-4 w-4" />
          {t("studio.add")}
        </Button>
      </TabActions>
      {!items.length ? (
        <EmptyState title={t("studio.empty")} />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {items.map((c) => (
            <ItemCard
              key={c.id}
              testId={`credential-${c.id}`}
              title={c.name}
              badges={<StatusBadge status={c.status} />}
              meta={
                <>
                  <span className="font-mono" data-testid={`credential-hint-${c.id}`}>
                    {c.masked_hint}
                  </span>
                  {` · ${providerName(c.provider_id)} · ${t("studio.weight")} ${c.weight}`}
                  {c.disabled_reason ? ` · ${c.disabled_reason}` : ""}
                </>
              }
              actions={
                <>
                  <Button size="sm" variant="outline" onClick={() => setEditing(c)}>
                    {t("studio.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setDeleting(c)}>
                    {t("studio.delete")}
                  </Button>
                </>
              }
            />
          ))}
        </ul>
      )}
      {editing && <CredentialDialog credential={editing === "new" ? null : editing} providers={providers.data ?? []} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("studio.delete")}
        description={t("studio.deleteConfirm", { name: deleting?.name ?? "" })}
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}
