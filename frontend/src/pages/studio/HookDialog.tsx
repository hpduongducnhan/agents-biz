import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { type Hook, studioApi } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Button, Checkbox, Field, FormDialog, Input, JsonView, Label, NativeSelect, Textarea } from "@/ui";

import { JsonField, parseJson, useStudioMutation } from "./common";

type Point = "before_run" | "before_tool" | "after_tool" | "after_run";
type Cond = { path: string; op: string; value: string };
const POINTS: Point[] = ["before_run", "before_tool", "after_tool", "after_run"];
const OPS = ["eq", "ne", "in", "contains", "exists", "gt", "gte", "lt", "lte"];
const ALLOWED: Record<Point, string[]> = {
  before_run: ["block", "add_context", "notify", "webhook"],
  before_tool: ["block", "require_approval", "notify", "webhook"],
  after_tool: ["notify", "webhook"],
  after_run: ["notify", "webhook"],
};
const SAMPLE: Record<Point, object> = {
  before_run: { user: { id: "u1", name: "An" }, agent: { slug: "assistant" }, message: { text: "tôi có thông báo nào mới không" } },
  before_tool: { user: { id: "u1" }, agent: { slug: "assistant" }, tool: { name: "notifications_list", toolset: "lookup", effect: "read" }, args: { limit: 20 } },
  after_tool: { user: { id: "u1" }, agent: { slug: "assistant" }, tool: { name: "notifications_list" }, args: {}, result: { ok: false, error_code: 1005 } },
  after_run: { user: { id: "u1" }, agent: { slug: "assistant" }, run: { status: "done", tokens: { input: 1200, output: 80 }, tools: [] } },
};

/** Giá trị gõ chữ → JSON khi được (số, true, mảng…), không thì giữ chuỗi. */
const valueOf = (raw: string): unknown => {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
};

export function HookDialog({ agentId, hook, onClose }: { agentId: string; hook: Hook | null; onClose: () => void }) {
  const t = useT();
  const cfg = (hook?.action_config ?? {}) as Record<string, unknown>;
  const [name, setName] = useState(hook?.name ?? "");
  const [point, setPoint] = useState<Point>((hook?.point as Point) ?? "before_tool");
  const [conds, setConds] = useState<Cond[]>(() =>
    ((hook?.conditions ?? []) as { path: string; op: string; value?: unknown }[]).map((c) => ({ path: c.path, op: c.op, value: typeof c.value === "string" ? c.value : JSON.stringify(c.value ?? "") })),
  );
  const [action, setAction] = useState(hook?.action ?? "require_approval");
  const [text, setText] = useState(String(cfg.message ?? cfg.text ?? ""));
  const [to, setTo] = useState(String(cfg.to ?? "superadmins"));
  const [url, setUrl] = useState(String(cfg.url ?? ""));
  const [position, setPosition] = useState(String(hook?.position ?? 0));
  const [enabled, setEnabled] = useState(hook?.enabled ?? true);
  const [sample, setSample] = useState(JSON.stringify(SAMPLE[point], null, 2));
  const [result, setResult] = useState<unknown>(null);
  const [testing, setTesting] = useState(false);
  const allowed = ALLOWED[point];
  const act = allowed.includes(action) ? action : allowed[0]!;
  const actionBody = (): Record<string, unknown> => {
    if (act === "block") return { action: act, message: text };
    if (act === "add_context") return { action: act, text };
    if (act === "notify") return { action: act, to, text };
    if (act === "webhook") return { action: act, url };
    return { action: act };
  };
  const conditions = conds.filter((c) => c.path.trim()).map((c) => ({ path: c.path.trim(), op: c.op, value: c.op === "exists" ? true : valueOf(c.value) }));
  const save = useStudioMutation(studioApi.saveHook, [STUDIO.hooks(agentId), STUDIO.agent(agentId)], onClose);
  const s = parseJson(sample);
  const test = async () => {
    if (!s.ok) return;
    setTesting(true);
    try {
      setResult(await studioApi.testHook({ point, conditions, action: actionBody(), sample: s.value }));
    } catch (err) {
      toastError(err);
    } finally {
      setTesting(false);
    }
  };
  const needsText = act === "block" || act === "add_context" || act === "notify";
  return (
    <FormDialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title={hook ? hook.name || hook.action : t("studio.hook.add")}
      submitting={save.isPending}
      disabled={(needsText && !text.trim()) || (act === "webhook" && !url.trim())}
      onSubmit={() =>
        save.mutate({ hook_id: hook?.id ?? null, agent_id: agentId, name, point, conditions, action: actionBody(), position: Number(position) || 0, enabled })
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="hk-name" label={t("studio.name")}>
          <Input id="hk-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field id="hk-point" label={t("studio.hook.point")}>
          <NativeSelect
            id="hk-point"
            value={point}
            onChange={(e) => {
              setPoint(e.target.value as Point);
              setSample(JSON.stringify(SAMPLE[e.target.value as Point], null, 2));
            }}
          >
            {POINTS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </div>
      <div className="grid gap-2">
        <Label>{t("studio.hook.conditions")}</Label>
        {conds.map((c, i) => (
          <div key={i} className="grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2">
            <Input aria-label={t("studio.hook.path")} placeholder="args.amount" value={c.path} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, path: e.target.value } : x)))} />
            <NativeSelect aria-label={t("studio.hook.op")} className="w-auto" value={c.op} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))}>
              {OPS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </NativeSelect>
            <Input aria-label={t("studio.hook.value")} value={c.value} disabled={c.op === "exists"} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
            <Button type="button" variant="ghost" size="icon" aria-label={t("studio.delete")} onClick={() => setConds(conds.filter((_, j) => j !== i))}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
        {conds.length < 10 && (
          <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => setConds([...conds, { path: "", op: "eq", value: "" }])} data-testid="hook-add-condition">
            <Plus className="h-4 w-4" />
            {t("studio.hook.addCondition")}
          </Button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="hk-action" label={t("studio.hook.action")}>
          <NativeSelect id="hk-action" value={act} onChange={(e) => setAction(e.target.value)}>
            {allowed.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </NativeSelect>
        </Field>
        {act === "notify" && (
          <Field id="hk-to" label={t("studio.hook.to")}>
            <NativeSelect id="hk-to" value={to} onChange={(e) => setTo(e.target.value)}>
              <option value="user">{t("studio.hook.to.user")}</option>
              <option value="superadmins">{t("studio.hook.to.superadmins")}</option>
            </NativeSelect>
          </Field>
        )}
        {act === "webhook" && (
          <Field id="hk-url" label={t("studio.hook.url")}>
            <Input id="hk-url" value={url} placeholder="https://…" onChange={(e) => setUrl(e.target.value)} />
          </Field>
        )}
      </div>
      {needsText && (
        <Field id="hk-text" label={act === "block" ? t("studio.hook.message") : t("studio.hook.text")}>
          <Textarea id="hk-text" rows={2} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
      )}
      <div className="flex flex-wrap items-center gap-4">
        <Field id="hk-pos" label={t("studio.hook.position")}>
          <Input id="hk-pos" type="number" inputMode="numeric" className="w-24" value={position} onChange={(e) => setPosition(e.target.value)} />
        </Field>
        <span className="flex items-center gap-2 pt-6">
          <Checkbox id="hk-enabled" checked={enabled} onCheckedChange={(v) => setEnabled(v === true)} />
          <Label htmlFor="hk-enabled">{t("studio.hook.enabled")}</Label>
        </span>
      </div>
      <JsonField id="hk-sample" label={t("studio.hook.sample")} value={sample} onChange={setSample} />
      <Button type="button" variant="outline" className="w-fit" disabled={testing || !s.ok} onClick={() => void test()} data-testid="hook-test">
        {t("studio.hook.test")}
      </Button>
      {result ? (
        <div className="grid gap-1" data-testid="hook-test-result">
          <span className="text-sm font-semibold">{t("studio.hook.result")}</span>
          {(result as { matched?: boolean }).matched ? <JsonView value={result} maxHeight={240} defaultDepth={2} /> : <p className="text-sm text-muted-foreground">{t("studio.hook.noMatch")}</p>}
        </div>
      ) : null}
    </FormDialog>
  );
}
