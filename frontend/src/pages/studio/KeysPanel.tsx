import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { credentialsApi, studioApi, type StudioAgent } from "@/features/agent/api";
import { CREDENTIALS, STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Label } from "@/ui";

import { StatusBadge, useStudioMutation } from "./common";

/** Pool key của agent: tích chọn credential (key khác provider của model → backend báo lỗi). */
export function KeysPanel({ agent }: { agent: StudioAgent }) {
  const t = useT();
  const creds = useQuery({ queryKey: CREDENTIALS.list({ limit: 100 }), queryFn: () => credentialsApi.list({ limit: 100 }) });
  const [picked, setPicked] = useState<Set<string>>(() => new Set(agent.keys.filter((k) => k.enabled).map((k) => k.credential_id)));
  const save = useStudioMutation(studioApi.setKeys, [STUDIO.agents(), STUDIO.agent(agent.id)]);
  const toggle = (id: string, on: boolean) => {
    const next = new Set(picked);
    if (on) next.add(id);
    else next.delete(id);
    setPicked(next);
  };
  return (
    <Card data-testid="keys-panel">
      <CardHeader>
        <CardTitle>{t("studio.section.keys")}</CardTitle>
        <CardDescription>{t("studio.keysHint")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2">
        {(creds.data?.items ?? []).map((c) => (
          <label key={c.id} htmlFor={`key-${c.id}`} className="flex min-h-11 items-center gap-3 rounded-xl border border-border px-3 py-2">
            <Checkbox id={`key-${c.id}`} checked={picked.has(c.id)} onCheckedChange={(v) => toggle(c.id, v === true)} />
            <Label htmlFor={`key-${c.id}`} className="min-w-0 flex-1 truncate">
              {c.name} <span className="font-mono text-xs text-muted-foreground">{c.masked_hint}</span>
            </Label>
            <StatusBadge status={c.status} />
          </label>
        ))}
        <Button
          className="w-fit"
          disabled={save.isPending}
          onClick={() => save.mutate({ agent_id: agent.id, keys: [...picked].map((credential_id) => ({ credential_id, enabled: true })) })}
          data-testid="keys-save"
        >
          {t("studio.save")}
        </Button>
      </CardContent>
    </Card>
  );
}
