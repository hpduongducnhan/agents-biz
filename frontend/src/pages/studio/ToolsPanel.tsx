import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { studioApi, type StudioAgent } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Button, Card, CardContent, CardHeader, CardTitle, Checkbox, Label, NativeSelect, Skeleton } from "@/ui";

import { useStudioMutation } from "./common";

type Policy = "auto" | "confirm" | "deny";

/** Toolset của agent + chính sách từng tool (chỉ nâng: tự chạy → hỏi duyệt → cấm). Tool bị cấm rời danh sách hiệu lực. */
export function ToolsPanel({ agent }: { agent: StudioAgent }) {
  const t = useT();
  const catalog = useQuery({ queryKey: STUDIO.catalog(), queryFn: studioApi.catalog });
  const [sets, setSets] = useState<Set<string>>(() => new Set(agent.toolsets));
  const keys = [STUDIO.agents(), STUDIO.agent(agent.id)];
  const saveSets = useStudioMutation((names: string[]) => studioApi.setToolsets(agent.id, names), keys);
  const setOverride = useStudioMutation(studioApi.setOverride, keys);
  const policyOf = (op: string) => (agent.overrides.find((o) => o.operation === op)?.policy as Policy | null | undefined) ?? null;
  if (catalog.isLoading) return <Skeleton className="h-40 w-full" />;
  const active = (catalog.data ?? []).filter((ts) => agent.toolsets.includes(ts.toolset));
  const all = active.flatMap((ts) => ts.ops);
  const effective = all.filter((op) => policyOf(op.name) !== "deny");
  const denied = all.filter((op) => policyOf(op.name) === "deny");
  const onPolicy = (operation: string, policy: Policy | null) => setOverride.mutate({ agent_id: agent.id, operation, policy, remove: !policy });
  return (
    <Card data-testid="tools-panel">
      <CardHeader>
        <CardTitle>{t("studio.section.tools")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-2 sm:grid-cols-2">
          {(catalog.data ?? []).map((ts) => (
            <label key={ts.toolset} htmlFor={`ts-${ts.toolset}`} className="flex min-h-11 items-start gap-3 rounded-xl border border-border px-3 py-2">
              <Checkbox
                id={`ts-${ts.toolset}`}
                checked={sets.has(ts.toolset)}
                onCheckedChange={(v) => {
                  const next = new Set(sets);
                  if (v === true) next.add(ts.toolset);
                  else next.delete(ts.toolset);
                  setSets(next);
                }}
              />
              <span className="grid min-w-0">
                <Label htmlFor={`ts-${ts.toolset}`} className="font-mono">
                  {ts.toolset} ({ts.ops.length})
                </Label>
                <span className="text-xs text-muted-foreground">{ts.description}</span>
              </span>
            </label>
          ))}
        </div>
        <Button className="w-fit" disabled={saveSets.isPending} onClick={() => saveSets.mutate([...sets])} data-testid="toolsets-save">
          {t("studio.save")}
        </Button>
        <ToolList title={`${t("studio.effective")} (${effective.length})`} testId="effective-tools" ops={effective} policyOf={policyOf} onPolicy={onPolicy} />
        {denied.length ? <ToolList title={`${t("studio.policy.deny")} (${denied.length})`} testId="denied-tools" ops={denied} policyOf={policyOf} onPolicy={onPolicy} /> : null}
      </CardContent>
    </Card>
  );
}

type Op = { name: string; title: string; default_policy: string };

function ToolList(props: { title: string; testId: string; ops: Op[]; policyOf: (op: string) => Policy | null; onPolicy: (op: string, p: Policy | null) => void }) {
  const t = useT();
  return (
    <div className="grid gap-2">
      <span className="text-sm font-semibold">{props.title}</span>
      <ul className="grid gap-1" data-testid={props.testId}>
        {props.ops.map((op) => (
          <li key={op.name} className="flex min-w-0 flex-wrap items-center gap-2 rounded-xl border border-border px-3 py-2 text-sm" data-testid={`tool-${op.name}`}>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-semibold">{op.title}</span>
              <span className="block truncate font-mono text-xs text-muted-foreground">{op.name}</span>
            </span>
            <NativeSelect
              aria-label={t("studio.policy")}
              className="w-auto"
              value={props.policyOf(op.name) ?? ""}
              data-testid={`policy-${op.name}`}
              onChange={(e) => props.onPolicy(op.name, (e.target.value || null) as Policy | null)}
            >
              <option value="">{t("studio.policy.default", { p: t(`studio.policy.${op.default_policy}`) })}</option>
              <option value="confirm">{t("studio.policy.confirm")}</option>
              <option value="deny">{t("studio.policy.deny")}</option>
            </NativeSelect>
          </li>
        ))}
      </ul>
    </div>
  );
}
