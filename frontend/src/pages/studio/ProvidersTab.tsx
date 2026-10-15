import { useQuery } from "@tanstack/react-query";
import { ListPlus, PlugZap, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { credentialsApi, type Provider, studioApi } from "@/features/agent/api";
import { CREDENTIALS, STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Button, ConfirmDialog, EmptyState, FormDialog, NativeSelect, Skeleton } from "@/ui";

import { ItemCard, StatusBadge, TabActions, useStudioMutation } from "./common";
import { ProviderDialog } from "./ProviderDialog";
import { ProviderModelsDialog } from "./ProviderModelsDialog";

export function ProvidersTab() {
  const t = useT();
  const { data, isLoading } = useQuery({ queryKey: STUDIO.providers(), queryFn: studioApi.providers });
  const creds = useQuery({ queryKey: CREDENTIALS.list({ limit: 100 }), queryFn: () => credentialsApi.list({ limit: 100 }) });
  const [editing, setEditing] = useState<Provider | "new" | null>(null);
  const [deleting, setDeleting] = useState<Provider | null>(null);
  const [testing, setTesting] = useState<Provider | null>(null);
  const [picking, setPicking] = useState<Provider | null>(null);
  const [credId, setCredId] = useState("");
  const [busy, setBusy] = useState(false);
  const remove = useStudioMutation((id: string) => studioApi.deleteProvider(id), [STUDIO.providers(), STUDIO.models()], () => setDeleting(null));
  const test = async () => {
    if (!testing || !credId) return;
    setBusy(true);
    try {
      const out = await studioApi.testProvider(testing.id, credId);
      if (out.ok) toast.success(t("studio.testOk", { ms: out.latency_ms, n: out.models?.length ?? 0 }));
      else toast.error(t("studio.testFail", { error: out.error ?? "" }));
      setTesting(null);
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  };
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  const usable = (creds.data?.items ?? []).filter((c) => !c.provider_id || c.provider_id === testing?.id);
  return (
    <div className="grid gap-3">
      <TabActions>
        <Button onClick={() => setEditing("new")} data-testid="provider-add">
          <Plus className="h-4 w-4" />
          {t("studio.add")}
        </Button>
      </TabActions>
      {!data?.length ? (
        <EmptyState title={t("studio.empty")} />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {data.map((p) => (
            <ItemCard
              key={p.id}
              testId={`provider-${p.id}`}
              title={p.name}
              badges={<StatusBadge status={p.status} />}
              meta={`${p.kind}${p.base_url ? ` · ${p.base_url}` : ""} · ${t("studio.modelsCount", { n: p.models_count })}`}
              actions={
                <>
                  <Button size="sm" variant="outline" onClick={() => setPicking(p)} data-testid={`provider-models-${p.id}`}>
                    <ListPlus className="h-4 w-4" />
                    {t("studio.pickModels")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setTesting(p)} aria-label={t("studio.testProvider")} data-testid={`provider-test-${p.id}`}>
                    <PlugZap className="h-4 w-4" />
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setEditing(p)}>
                    {t("studio.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setDeleting(p)}>
                    {t("studio.delete")}
                  </Button>
                </>
              }
            />
          ))}
        </ul>
      )}
      {editing && <ProviderDialog provider={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {picking && <ProviderModelsDialog providers={data ?? []} providerId={picking.id} onClose={() => setPicking(null)} />}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("studio.delete")}
        description={t("studio.deleteConfirm", { name: deleting?.name ?? "" })}
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
      {testing && (
        <FormDialog open onOpenChange={(o) => !o && setTesting(null)} title={t("studio.testProvider")} submitLabel={t("studio.testProvider")} submitting={busy} disabled={!credId} onSubmit={() => void test()}>
          <NativeSelect aria-label={t("studio.testWith")} value={credId} onChange={(e) => setCredId(e.target.value)} data-testid="provider-test-key">
            <option value="">{t("studio.testWith")}</option>
            {usable.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.masked_hint}
              </option>
            ))}
          </NativeSelect>
        </FormDialog>
      )}
    </div>
  );
}
