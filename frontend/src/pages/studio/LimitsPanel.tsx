import { useState } from "react";

import { studioApi, type StudioAgent } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input } from "@/ui";

import { useStudioMutation } from "./common";

const FIELDS = ["per_minute", "per_hour", "per_day", "tokens_per_day"] as const;

/** Hạn mức mặc định mỗi user của agent (trống = không giới hạn); ghi đè theo user làm ở bước sau. */
export function LimitsPanel({ agent }: { agent: StudioAgent }) {
  const t = useT();
  const [v, setV] = useState<Record<(typeof FIELDS)[number], string>>(() =>
    Object.fromEntries(FIELDS.map((k) => [k, agent.limits[k] == null ? "" : String(agent.limits[k])])) as Record<(typeof FIELDS)[number], string>,
  );
  const save = useStudioMutation(studioApi.setLimits, [STUDIO.agents(), STUDIO.agent(agent.id)]);
  const value = (k: (typeof FIELDS)[number]) => (v[k] && Number(v[k]) >= 1 ? Math.floor(Number(v[k])) : null);
  return (
    <Card data-testid="limits-panel">
      <CardHeader>
        <CardTitle>{t("studio.section.limits")}</CardTitle>
        <CardDescription>{t("studio.limitHint")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {FIELDS.map((k) => (
          <Field key={k} id={`lim-${k}`} label={t(`studio.limit.${k}`)}>
            <Input id={`lim-${k}`} type="number" inputMode="numeric" min={1} value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
          </Field>
        ))}
        <Button
          className="w-fit sm:col-span-2 lg:col-span-4"
          disabled={save.isPending}
          onClick={() => save.mutate({ agent_id: agent.id, ...Object.fromEntries(FIELDS.map((k) => [k, value(k)])) })}
          data-testid="limits-save"
        >
          {t("studio.save")}
        </Button>
      </CardContent>
    </Card>
  );
}
