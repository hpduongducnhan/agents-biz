import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { type SettingsPatch, systemApi, type SystemSettings } from "@/features/system/api";
import { SYSTEM } from "@/features/system/keys";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Field, Input, Label, Skeleton, Switch } from "@/ui";

import { ChatBlocksPanel } from "./ChatBlocksPanel";

/** Khoá số của trang + khoảng cho phép (khớp `SystemSettings` backend). */
const LIMITS = { chat_per_minute: [0, 100_000], chat_per_hour: [0, 100_000], chat_per_day: [0, 100_000] } as const;
const AUTO = { chat_autoblock_strikes: [1, 100], chat_autoblock_window_min: [1, 1440], chat_autoblock_minutes: [1, 10_080] } as const;
const RANGES = { ...LIMITS, ...AUTO };
type NumKey = keyof typeof RANGES;
type Draft = Record<NumKey, string> & { chat_autoblock: boolean };

const KEYS = Object.keys(RANGES) as NumKey[];
const valid = (k: NumKey, v: string) => /^\d+$/.test(v.trim()) && Number(v) >= RANGES[k][0] && Number(v) <= RANGES[k][1];

function toDraft(s: SystemSettings): Draft {
  return { ...(Object.fromEntries(KEYS.map((k) => [k, String(s[k])])) as Record<NumKey, string>), chat_autoblock: s.chat_autoblock };
}

function diff(s: SystemSettings, d: Draft): SettingsPatch {
  const patch: SettingsPatch = {};
  if (d.chat_autoblock !== s.chat_autoblock) patch.chat_autoblock = d.chat_autoblock;
  for (const k of KEYS) if (valid(k, d[k]) && Number(d[k]) !== s[k]) patch[k] = Number(d[k]);
  return patch;
}

/** /sa/chat-guard — chống spam trợ lý: hạn mức mặc định, luật tự chặn, danh sách đang bị chặn + lịch sử. */
export default function ChatGuardPage() {
  const { data } = useQuery({ queryKey: SYSTEM.settings(), queryFn: () => systemApi.getSettings() });
  return (
    <div className="grid gap-4">
      {data ? <GuardForm key={JSON.stringify(data)} settings={data} /> : <Skeleton className="h-48 w-full" />}
      <ChatBlocksPanel />
    </div>
  );
}

function GuardForm({ settings }: { settings: SystemSettings }) {
  const t = useT();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => toDraft(settings));
  const patch = diff(settings, draft);
  const ok = KEYS.every((k) => valid(k, draft[k]));
  const dirty = Object.keys(patch).length > 0;
  const save = useMutation({
    mutationFn: () => systemApi.updateSettings(patch),
    onSuccess: (next) => {
      qc.setQueryData(SYSTEM.settings(), next);
      toast.success(t("guard.saved"));
    },
    onError: (err) => toastError(err),
  });

  const field = (k: NumKey) => (
    <Field
      key={k}
      id={`cg-${k}`}
      label={
        <span className="flex flex-wrap items-center gap-2">
          {t(`guard.field.${k}`)}
          {settings.defaults_applied.includes(k) ? (
            <Badge variant="outline" data-testid={`guard-default-${k}`}>
              {t("sa.settings.isDefault")}
            </Badge>
          ) : null}
        </span>
      }
      error={valid(k, draft[k]) ? undefined : t("guard.invalid")}
    >
      <Input id={`cg-${k}`} inputMode="numeric" className="num" data-testid={`guard-field-${k}`} value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
    </Field>
  );

  return (
    <form
      className="grid grid-cols-1 gap-4 xl:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty && ok) save.mutate();
      }}
    >
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="text-base">{t("guard.limits")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("guard.limitsHint")}</p>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-3">{(Object.keys(LIMITS) as NumKey[]).map(field)}</CardContent>
      </Card>
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="text-base">{t("guard.auto")}</CardTitle>
          <p className="text-xs text-muted-foreground" data-testid="guard-rule">
            {draft.chat_autoblock
              ? t("guard.autoRule", { n: draft.chat_autoblock_strikes, m: draft.chat_autoblock_window_min, t: draft.chat_autoblock_minutes })
              : t("guard.autoOff")}
          </p>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-center justify-between gap-4 rounded-xl border border-border p-3">
            <Label htmlFor="cg-auto">{t("guard.autoToggle")}</Label>
            <Switch id="cg-auto" data-testid="guard-autoblock" checked={draft.chat_autoblock} onCheckedChange={(v) => setDraft({ ...draft, chat_autoblock: v })} />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">{(Object.keys(AUTO) as NumKey[]).map(field)}</div>
        </CardContent>
      </Card>
      <div className="flex justify-end xl:col-span-2">
        <Button type="submit" disabled={!dirty || !ok || save.isPending} data-testid="guard-save">
          {t("common.save")}
        </Button>
      </div>
    </form>
  );
}
