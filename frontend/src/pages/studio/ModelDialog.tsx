import { useState } from "react";

import { type Model, type Provider, studioApi } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Field, FormDialog, Input, NativeSelect } from "@/ui";

import { useStudioMutation } from "./common";

const PRICES = [
  ["input_price_per_1m", "studio.priceIn"],
  ["output_price_per_1m", "studio.priceOut"],
  ["cache_read_price_per_1m", "studio.priceCacheRead"],
  ["cache_write_price_per_1m", "studio.priceCacheWrite"],
] as const;
type PriceKey = (typeof PRICES)[number][0];

export function ModelDialog({ model, providers, onClose }: { model: Model | null; providers: Provider[]; onClose: () => void }) {
  const t = useT();
  const [providerId, setProviderId] = useState(model?.provider_id ?? providers[0]?.id ?? "");
  const [modelId, setModelId] = useState(model?.model_id ?? "");
  const [name, setName] = useState(model?.name ?? "");
  const [prices, setPrices] = useState<Record<PriceKey, string>>({
    input_price_per_1m: String(model?.input_price_per_1m ?? "0"),
    output_price_per_1m: String(model?.output_price_per_1m ?? "0"),
    cache_read_price_per_1m: String(model?.cache_read_price_per_1m ?? "0"),
    cache_write_price_per_1m: String(model?.cache_write_price_per_1m ?? "0"),
  });
  const [ctx, setCtx] = useState(model?.context_window ? String(model.context_window) : "");
  const save = useStudioMutation(studioApi.saveModel, [STUDIO.models(), STUDIO.agents()], onClose);
  const valid = providerId && modelId.trim() && name.trim() && PRICES.every(([k]) => Number(prices[k]) >= 0);
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={model ? model.name : t("studio.add")}
      submitting={save.isPending}
      disabled={!valid}
      onSubmit={() =>
        save.mutate({
          model_ref: model?.id ?? null,
          provider_id: providerId,
          model_id: modelId.trim(),
          name: name.trim(),
          ...Object.fromEntries(PRICES.map(([k]) => [k, prices[k] || "0"])),
          context_window: ctx ? Number(ctx) : null,
        })
      }
    >
      <Field id="md-provider" label={t("studio.provider")}>
        <NativeSelect id="md-provider" value={providerId} onChange={(e) => setProviderId(e.target.value)}>
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="md-id" label={t("studio.modelId")}>
        <Input id="md-id" value={modelId} onChange={(e) => setModelId(e.target.value)} placeholder="gpt-5-mini" />
      </Field>
      <Field id="md-name" label={t("studio.name")}>
        <Input id="md-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        {PRICES.map(([k, label]) => (
          <Field key={k} id={`md-${k}`} label={t(label)}>
            <Input id={`md-${k}`} type="number" inputMode="decimal" min={0} step="0.0001" value={prices[k]} onChange={(e) => setPrices({ ...prices, [k]: e.target.value })} />
          </Field>
        ))}
      </div>
      <Field id="md-ctx" label={t("studio.contextWindow")}>
        <Input id="md-ctx" type="number" inputMode="numeric" min={1} value={ctx} onChange={(e) => setCtx(e.target.value)} />
      </Field>
    </FormDialog>
  );
}
