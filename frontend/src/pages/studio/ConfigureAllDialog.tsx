import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { credentialsApi, studioApi } from "@/features/agent/api";
import { AGENT, CREDENTIALS, STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Checkbox, Field, FormDialog, Label, NativeSelect } from "@/ui";

import { useStudioMutation } from "./common";

/** Gắn một model + pool key cho orchestrator và mọi chuyên gia trong một lần (cấu hình prod lần đầu). */
export function ConfigureAllDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const models = useQuery({ queryKey: STUDIO.models(), queryFn: studioApi.models });
  const creds = useQuery({ queryKey: CREDENTIALS.list({ limit: 100 }), queryFn: () => credentialsApi.list({ limit: 100 }) });
  const [modelId, setModelId] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const model = (models.data ?? []).find((m) => m.id === modelId);
  const usable = (creds.data?.items ?? []).filter((c) => c.status === "active" && (!c.provider_id || !model || c.provider_id === model.provider_id));
  const save = useStudioMutation(studioApi.configureAll, [STUDIO.agents(), STUDIO.all, AGENT.agents()], onClose);
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t("studio.configureAll")}
      submitting={save.isPending}
      disabled={!modelId || picked.size === 0}
      onSubmit={() => save.mutate({ model_id: modelId, credential_ids: [...picked] })}
    >
      <p className="text-sm text-muted-foreground">{t("studio.configureAllHint")}</p>
      <Field id="ca-model" label={t("studio.model")}>
        <NativeSelect id="ca-model" value={modelId} onChange={(e) => setModelId(e.target.value)} data-testid="configure-all-model">
          <option value="">{t("studio.noModel")}</option>
          {(models.data ?? []).map((m) => (
            <option key={m.id} value={m.id}>
              {m.provider_name} · {m.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <div className="grid gap-2">
        <Label>{t("studio.section.keys")}</Label>
        {usable.map((c) => (
          <label key={c.id} htmlFor={`ca-${c.id}`} className="flex min-h-11 items-center gap-3 rounded-xl border border-border px-3 py-2">
            <Checkbox
              id={`ca-${c.id}`}
              checked={picked.has(c.id)}
              onCheckedChange={(v) => {
                const next = new Set(picked);
                if (v === true) next.add(c.id);
                else next.delete(c.id);
                setPicked(next);
              }}
            />
            <span className="min-w-0 flex-1 truncate text-sm">
              {c.name} <span className="font-mono text-xs text-muted-foreground">{c.masked_hint}</span>
            </span>
          </label>
        ))}
      </div>
    </FormDialog>
  );
}
