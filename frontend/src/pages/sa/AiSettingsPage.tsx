import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type SettingsPatch, systemApi, type SystemSettings } from "@/features/system/api";
import { SYSTEM } from "@/features/system/keys";
import { useT } from "@/lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, Skeleton } from "@/ui";

import { DefaultBadge, inRange, isUint, NumField, SaveBar, ToggleRow, useSaveSettings } from "./settings/shared";

/** Giới hạn khớp `system_settings` ở backend. */
const CHAT_NUMERIC = ["chat_session_idle_min", "chat_history_limit"] as const;
const FLUSH = { min: 20, max: 1000 } as const;
type ChatNumKey = (typeof CHAT_NUMERIC)[number];
type Draft = { chat_history_tools: boolean; chat_stream: boolean; chat_stream_flush_ms: string } & Record<ChatNumKey, string>;

function toDraft(s: SystemSettings): Draft {
  return {
    chat_session_idle_min: String(s.chat_session_idle_min),
    chat_history_limit: String(s.chat_history_limit),
    chat_history_tools: s.chat_history_tools,
    chat_stream: s.chat_stream,
    chat_stream_flush_ms: String(s.chat_stream_flush_ms),
  };
}

function diff(s: SystemSettings, d: Draft): SettingsPatch {
  const patch: SettingsPatch = {};
  if (d.chat_history_tools !== s.chat_history_tools) patch.chat_history_tools = d.chat_history_tools;
  if (d.chat_stream !== s.chat_stream) patch.chat_stream = d.chat_stream;
  for (const k of CHAT_NUMERIC) if (isUint(d[k]) && Number(d[k]) !== s[k]) patch[k] = Number(d[k]);
  if (inRange(d.chat_stream_flush_ms, FLUSH.min, FLUSH.max) && Number(d.chat_stream_flush_ms) !== s.chat_stream_flush_ms) patch.chat_stream_flush_ms = Number(d.chat_stream_flush_ms);
  return patch;
}

/** AI → Cài đặt (`/sa/ai-settings`): cài đặt Trợ lý chat (chuyển từ Cài đặt hệ thống) + trả lời dạng stream. */
export default function AiSettingsPage() {
  const { data } = useQuery({ queryKey: SYSTEM.settings(), queryFn: () => systemApi.getSettings() });
  if (!data) return <Skeleton className="h-64 w-full" />;
  return <AiSettingsForm key={JSON.stringify(data)} settings={data} />;
}

function AiSettingsForm({ settings }: { settings: SystemSettings }) {
  const t = useT();
  const [draft, setDraft] = useState<Draft>(() => toDraft(settings));
  const patch = diff(settings, draft);
  const flushOk = inRange(draft.chat_stream_flush_ms, FLUSH.min, FLUSH.max);
  const valid = CHAT_NUMERIC.every((k) => isUint(draft[k])) && flushOk;
  const dirty = Object.keys(patch).length > 0;
  const isDefault = (k: string) => settings.defaults_applied.includes(k);
  const save = useSaveSettings(patch);

  return (
    <form
      className="grid grid-cols-1 gap-4 xl:grid-cols-2"
      data-testid="ai-settings"
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty && valid) save.mutate();
      }}
    >
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="text-base">{t("sa.settings.chat")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("sa.settings.chatHint")}</p>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {CHAT_NUMERIC.map((k) => (
            <NumField
              key={k}
              k={k}
              label={t(`sa.settings.field.${k}`)}
              value={draft[k]}
              error={isUint(draft[k]) ? undefined : t("sa.settings.invalid")}
              isDefault={isDefault(k)}
              onChange={(v) => setDraft({ ...draft, [k]: v })}
            />
          ))}
          <div className="sm:col-span-2">
            <ToggleRow
              id="ss-chat-tools"
              testId="settings-chat-tools"
              label={<span className="flex flex-wrap items-center gap-2">{t("sa.settings.chatTools")}<DefaultBadge k="chat_history_tools" on={isDefault("chat_history_tools")} /></span>}
              hint={t("sa.settings.chatToolsHint")}
              checked={draft.chat_history_tools}
              onChange={(v) => setDraft({ ...draft, chat_history_tools: v })}
            />
          </div>
        </CardContent>
      </Card>
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="text-base">{t("sa.ai.stream")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("sa.ai.streamHint")}</p>
        </CardHeader>
        <CardContent className="grid gap-4">
          <ToggleRow
            id="ss-chat-stream"
            testId="settings-chat-stream"
            label={<span className="flex flex-wrap items-center gap-2">{t("sa.ai.streamOn")}<DefaultBadge k="chat_stream" on={isDefault("chat_stream")} /></span>}
            hint={draft.chat_stream ? t("sa.ai.streamOnHint") : t("sa.ai.streamOffHint")}
            checked={draft.chat_stream}
            onChange={(v) => setDraft({ ...draft, chat_stream: v })}
          />
          <NumField
            k="chat_stream_flush_ms"
            label={t("sa.settings.field.chat_stream_flush_ms")}
            value={draft.chat_stream_flush_ms}
            hint={t("sa.ai.flushHint")}
            error={flushOk ? undefined : t("sa.ai.flushInvalid", { min: FLUSH.min, max: FLUSH.max })}
            isDefault={isDefault("chat_stream_flush_ms")}
            disabled={!draft.chat_stream}
            onChange={(v) => setDraft({ ...draft, chat_stream_flush_ms: v })}
          />
        </CardContent>
      </Card>
      <SaveBar disabled={!dirty || !valid || save.isPending} />
    </form>
  );
}
