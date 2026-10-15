import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type StudioAgent, studioApi } from "@/features/agent/api";
import { AGENT, STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Button, Card, CardContent, CardHeader, CardTitle, Checkbox, Field, Input, Label, NativeSelect, Textarea } from "@/ui";

import { JsonField, jsonText, parseJson, useStudioMutation } from "./common";

const num = (v: string, d: number) => (Number.isFinite(Number(v)) && v !== "" ? Number(v) : d);

/** Phần cơ bản của agent: tên, hướng dẫn, model, giới hạn bước / thời gian, chiến lược key, ai được chat. */
export function AgentEditor({ agent, onSaved }: { agent: StudioAgent | null; onSaved: (id: string) => void }) {
  const t = useT();
  const models = useQuery({ queryKey: STUDIO.models(), queryFn: studioApi.models });
  const [f, setF] = useState({
    slug: agent?.slug ?? "",
    name: agent?.name ?? "",
    description: agent?.description ?? "",
    instructions: agent?.instructions ?? "",
    persona_shared: agent?.persona_shared ?? true,
    starters: (agent?.starters ?? []).map(String).join("\n"),
    model_id: agent?.model_id ?? "",
    recursion_limit: String(agent?.recursion_limit ?? 25),
    timeout_sec: String(agent?.timeout_sec ?? 90),
    kind: (agent?.kind ?? "specialist") as "specialist" | "orchestrator",
    key_strategy: (agent?.key_strategy ?? "round_robin") as "round_robin" | "auto",
    key_cooldown_sec: String(agent?.key_cooldown_sec ?? 300),
    visible_to: (agent?.visible_to ?? "all") as "all" | "roles",
    visible_roles: (agent?.visible_roles ?? []).map(String).join(", "),
    is_active: agent?.is_active ?? true,
  });
  const [params, setParams] = useState(jsonText(agent?.params_override));
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF({ ...f, [k]: v });
  const p = parseJson(params);
  const save = useStudioMutation(studioApi.saveAgent, [STUDIO.agents(), STUDIO.agent(agent?.id ?? ""), AGENT.agents()], (out) => onSaved(out.id));
  const submit = () =>
    p.ok &&
    save.mutate({
      agent_id: agent?.id ?? null,
      slug: f.slug.trim(),
      name: f.name.trim(),
      kind: f.kind,
      description: f.description,
      instructions: f.instructions,
      persona_shared: f.persona_shared,
      starters: f.starters.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 8),
      model_id: f.model_id || null,
      params_override: p.value,
      recursion_limit: num(f.recursion_limit, 25),
      timeout_sec: num(f.timeout_sec, 90),
      key_strategy: f.key_strategy,
      key_cooldown_sec: num(f.key_cooldown_sec, 300),
      visible_to: f.visible_to,
      visible_roles: f.visible_roles.split(",").map((s) => s.trim()).filter(Boolean),
      is_active: f.is_active,
    });
  const numbers = [
    ["recursion_limit", "studio.recursionLimit"],
    ["timeout_sec", "studio.timeout"],
    ["key_cooldown_sec", "studio.cooldown"],
  ] as const;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("studio.section.basics")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4 md:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Field id="ag-name" label={t("studio.name")}>
            <Input id="ag-name" value={f.name} maxLength={100} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field id="ag-slug" label={t("studio.slug")}>
            <Input id="ag-slug" value={f.slug} maxLength={64} onChange={(e) => set("slug", e.target.value)} />
          </Field>
          <Field id="ag-model" label={t("studio.model")}>
            <NativeSelect id="ag-model" value={f.model_id} onChange={(e) => set("model_id", e.target.value)} data-testid="agent-model">
              <option value="">{t("studio.noModel")}</option>
              {(models.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.provider_name} · {m.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id="ag-kind" label={t("studio.agentKind")}>
            <NativeSelect id="ag-kind" value={f.kind} onChange={(e) => set("kind", e.target.value as typeof f.kind)} data-testid="agent-kind">
              <option value="specialist">{t("studio.kind.specialist")}</option>
              <option value="orchestrator">{t("studio.kind.orchestrator")}</option>
            </NativeSelect>
          </Field>
          <Field id="ag-strategy" label={t("studio.keyStrategy")}>
            <NativeSelect id="ag-strategy" value={f.key_strategy} onChange={(e) => set("key_strategy", e.target.value as typeof f.key_strategy)}>
              <option value="round_robin">{t("studio.keyStrategy.round_robin")}</option>
              <option value="auto">{t("studio.keyStrategy.auto")}</option>
            </NativeSelect>
          </Field>
          <div className="md:col-span-2">
            <Field id="ag-desc" label={t("studio.description")}>
              <Input id="ag-desc" value={f.description} maxLength={2000} onChange={(e) => set("description", e.target.value)} />
            </Field>
          </div>
          <div className="md:col-span-2">
            <Field id="ag-instr" label={t("studio.instructions")}>
              <Textarea id="ag-instr" rows={8} className="font-mono text-xs" value={f.instructions} onChange={(e) => set("instructions", e.target.value)} />
            </Field>
          </div>
          <div className="md:col-span-2">
            <Field id="ag-starters" label={t("studio.starters")}>
              <Textarea id="ag-starters" rows={3} value={f.starters} onChange={(e) => set("starters", e.target.value)} />
            </Field>
          </div>
          {numbers.map(([k, label]) => (
            <Field key={k} id={`ag-${k}`} label={t(label)}>
              <Input id={`ag-${k}`} type="number" inputMode="numeric" value={f[k]} onChange={(e) => set(k, e.target.value)} />
            </Field>
          ))}
          <Field id="ag-visible" label={t("studio.visibleTo")}>
            <NativeSelect id="ag-visible" value={f.visible_to} onChange={(e) => set("visible_to", e.target.value as typeof f.visible_to)}>
              <option value="all">{t("studio.visibleTo.all")}</option>
              <option value="roles">{t("studio.visibleTo.roles")}</option>
            </NativeSelect>
          </Field>
          {f.visible_to === "roles" && (
            <Field id="ag-roles" label={t("studio.visibleRoles")}>
              <Input id="ag-roles" value={f.visible_roles} onChange={(e) => set("visible_roles", e.target.value)} />
            </Field>
          )}
          <div className="md:col-span-2">
            <JsonField id="ag-params" label={t("studio.params")} value={params} onChange={setParams} />
          </div>
          <div className="flex flex-wrap items-center gap-4 md:col-span-2">
            <span className="flex items-center gap-2">
              <Checkbox id="ag-persona" checked={f.persona_shared} onCheckedChange={(v) => set("persona_shared", v === true)} />
              <Label htmlFor="ag-persona">{t("studio.personaShared")}</Label>
            </span>
            <span className="flex items-center gap-2">
              <Checkbox id="ag-active" checked={f.is_active} onCheckedChange={(v) => set("is_active", v === true)} />
              <Label htmlFor="ag-active">{t("studio.active")}</Label>
            </span>
            <Button type="submit" className="ml-auto" disabled={save.isPending || !f.name.trim() || !f.slug.trim() || !p.ok} data-testid="agent-save">
              {t("studio.save")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
