import { useState } from "react";

import { type Route, studioApi, type StudioAgent } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Checkbox, Field, FormDialog, Input, Label, NativeSelect, Textarea } from "@/ui";

import { useStudioMutation } from "./common";

type Props = { orchestratorId: string; route: Route | null; specialists: StudioAgent[]; onClose: () => void };

export function RouteDialog({ orchestratorId, route, specialists, onClose }: Props) {
  const t = useT();
  const [agentId, setAgentId] = useState(route?.agent_id ?? specialists[0]?.id ?? "");
  const [intent, setIntent] = useState(route?.intent ?? "");
  const [examples, setExamples] = useState((route?.examples ?? []).join("\n"));
  const [position, setPosition] = useState(String(route?.position ?? 0));
  const [enabled, setEnabled] = useState(route?.enabled ?? true);
  const save = useStudioMutation(studioApi.saveRoute, [STUDIO.routes(orchestratorId), STUDIO.agent(orchestratorId)], onClose);
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={route ? route.name : t("studio.route.add")}
      submitting={save.isPending}
      disabled={!agentId || !intent.trim()}
      onSubmit={() =>
        save.mutate({
          orchestrator_id: orchestratorId,
          agent_id: agentId,
          intent: intent.trim(),
          examples: examples.split("\n").map((x) => x.trim()).filter(Boolean).slice(0, 20),
          position: Number(position) || 0,
          enabled,
        })
      }
    >
      <Field id="rt-agent" label={t("studio.route.target")}>
        <NativeSelect id="rt-agent" value={agentId} disabled={!!route} onChange={(e) => setAgentId(e.target.value)} data-testid="route-target">
          {specialists.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.slug})
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="rt-intent" label={t("studio.route.intent")}>
        <Textarea id="rt-intent" rows={2} maxLength={1000} value={intent} onChange={(e) => setIntent(e.target.value)} data-testid="route-intent" />
      </Field>
      <Field id="rt-examples" label={t("studio.route.examples")}>
        <Textarea id="rt-examples" rows={5} value={examples} onChange={(e) => setExamples(e.target.value)} data-testid="route-examples" />
      </Field>
      <div className="flex flex-wrap items-end gap-4">
        <Field id="rt-pos" label={t("studio.hook.position")}>
          <Input id="rt-pos" type="number" inputMode="numeric" className="w-24" value={position} onChange={(e) => setPosition(e.target.value)} />
        </Field>
        <span className="flex min-h-11 items-center gap-2">
          <Checkbox id="rt-enabled" checked={enabled} onCheckedChange={(v) => setEnabled(v === true)} />
          <Label htmlFor="rt-enabled">{t("studio.hook.enabled")}</Label>
        </span>
      </div>
    </FormDialog>
  );
}
