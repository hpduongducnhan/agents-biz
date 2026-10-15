import { useQuery } from "@tanstack/react-query";
import { ListPlus, Plus } from "lucide-react";
import { useState } from "react";

import { type Model, studioApi } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Button, ConfirmDialog, EmptyState, Skeleton } from "@/ui";

import { ItemCard, StatusBadge, TabActions, useStudioMutation } from "./common";
import { ModelDialog } from "./ModelDialog";
import { ProviderModelsDialog } from "./ProviderModelsDialog";

export function ModelsTab() {
  const t = useT();
  const { data, isLoading } = useQuery({ queryKey: STUDIO.models(), queryFn: studioApi.models });
  const providers = useQuery({ queryKey: STUDIO.providers(), queryFn: studioApi.providers });
  const [editing, setEditing] = useState<Model | "new" | null>(null);
  const [deleting, setDeleting] = useState<Model | null>(null);
  const [picking, setPicking] = useState(false);
  const remove = useStudioMutation((id: string) => studioApi.deleteModel(id), [STUDIO.models(), STUDIO.agents()], () => setDeleting(null));
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="grid gap-3">
      <TabActions>
        <Button variant="outline" onClick={() => setEditing("new")} disabled={!providers.data?.length} data-testid="model-add">
          <Plus className="h-4 w-4" />
          {t("studio.add")}
        </Button>
        <Button onClick={() => setPicking(true)} disabled={!providers.data?.length} data-testid="model-import">
          <ListPlus className="h-4 w-4" />
          {t("studio.fromProvider")}
        </Button>
      </TabActions>
      {!data?.length ? (
        <EmptyState title={t("studio.empty")} />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {data.map((m) => (
            <ItemCard
              key={m.id}
              testId={`model-${m.id}`}
              title={m.name}
              badges={<StatusBadge status={m.status} />}
              meta={`${m.provider_name} · ${m.model_id} · $${Number(m.input_price_per_1m)} / $${Number(m.output_price_per_1m)}`}
              actions={
                <>
                  <Button size="sm" variant="outline" onClick={() => setEditing(m)}>
                    {t("studio.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setDeleting(m)}>
                    {t("studio.delete")}
                  </Button>
                </>
              }
            />
          ))}
        </ul>
      )}
      {picking && <ProviderModelsDialog providers={providers.data ?? []} onClose={() => setPicking(false)} />}
      {editing && <ModelDialog model={editing === "new" ? null : editing} providers={providers.data ?? []} onClose={() => setEditing(null)} />}
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
