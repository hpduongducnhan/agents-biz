import { useState } from "react";

import { type Provider, studioApi } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Field, FormDialog, Input, NativeSelect } from "@/ui";

import { JsonField, jsonText, parseJson, useStudioMutation } from "./common";

const KINDS = ["openai", "anthropic", "google_genai", "openai_compatible"] as const;

export function ProviderDialog({ provider, onClose }: { provider: Provider | null; onClose: () => void }) {
  const t = useT();
  const [name, setName] = useState(provider?.name ?? "");
  const [kind, setKind] = useState<(typeof KINDS)[number]>((provider?.kind as (typeof KINDS)[number]) ?? "openai");
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? "");
  const [headers, setHeaders] = useState(jsonText(provider?.extra_headers));
  const [params, setParams] = useState(jsonText(provider?.default_params));
  const [status, setStatus] = useState<"active" | "disabled">((provider?.status as "active" | "disabled") ?? "active");
  const h = parseJson(headers);
  const p = parseJson(params);
  const save = useStudioMutation(studioApi.saveProvider, [STUDIO.providers()], onClose);
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={provider ? provider.name : t("studio.add")}
      submitting={save.isPending}
      disabled={!name.trim() || !h.ok || !p.ok}
      onSubmit={() =>
        h.ok &&
        p.ok &&
        save.mutate({
          provider_id: provider?.id ?? null,
          name: name.trim(),
          kind,
          base_url: baseUrl.trim() || null,
          extra_headers: h.value as Record<string, string>,
          default_params: p.value,
          status,
        })
      }
    >
      <Field id="pv-name" label={t("studio.name")}>
        <Input id="pv-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field id="pv-kind" label={t("studio.kind")}>
        <NativeSelect id="pv-kind" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="pv-url" label={t("studio.baseUrl")}>
        <Input id="pv-url" value={baseUrl} placeholder="https://…" onChange={(e) => setBaseUrl(e.target.value)} />
      </Field>
      <JsonField id="pv-headers" label={t("studio.headers")} value={headers} onChange={setHeaders} />
      <JsonField id="pv-params" label={t("studio.params")} value={params} onChange={setParams} />
      <Field id="pv-status" label={t("studio.active")}>
        <NativeSelect id="pv-status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
          <option value="active">{t("studio.status.active")}</option>
          <option value="disabled">{t("studio.status.disabled")}</option>
        </NativeSelect>
      </Field>
    </FormDialog>
  );
}
