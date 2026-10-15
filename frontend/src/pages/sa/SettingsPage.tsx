import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { type SettingsPatch, systemApi, type SystemSettings } from "@/features/system/api";
import { SYSTEM } from "@/features/system/keys";
import { useT } from "@/lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, Field, NativeSelect, Skeleton } from "@/ui";

import { DefaultBadge, isUint, NumField, SaveBar, ToggleRow, useSaveSettings } from "./settings/shared";

const NUMERIC = ["user_limit_default", "event_log_ttl_days", "span_ttl_days", "raw_http_ttl_days"] as const;
const SIGNUP_MODES = ["default_tenant", "new_tenant", "invite_only"] as const;
const VERIFY_MODES = ["off", "soft", "required"] as const;
type SignupMode = (typeof SIGNUP_MODES)[number];
type VerifyMode = (typeof VERIFY_MODES)[number];
type NumKey = (typeof NUMERIC)[number];
type Draft = { signup_mode: SignupMode; email_verification: VerifyMode; google_enabled: boolean } & Record<NumKey, string>;

function toDraft(s: SystemSettings): Draft {
  return {
    signup_mode: s.signup_mode as SignupMode,
    email_verification: s.email_verification as VerifyMode,
    user_limit_default: String(s.user_limit_default),
    google_enabled: s.google_enabled,
    event_log_ttl_days: String(s.event_log_ttl_days),
    span_ttl_days: String(s.span_ttl_days),
    raw_http_ttl_days: String(s.raw_http_ttl_days),
  };
}

/** Chỉ gửi trường đã đổi — BE giữ nguyên trường không gửi. */
function diff(s: SystemSettings, d: Draft): SettingsPatch {
  const patch: SettingsPatch = {};
  if (d.signup_mode !== s.signup_mode) patch.signup_mode = d.signup_mode;
  if (d.email_verification !== s.email_verification) patch.email_verification = d.email_verification;
  if (d.google_enabled !== s.google_enabled) patch.google_enabled = d.google_enabled;
  for (const k of NUMERIC) if (isUint(d[k]) && Number(d[k]) !== s[k]) patch[k] = Number(d[k]);
  return patch;
}

export default function SettingsPage() {
  const { data } = useQuery({ queryKey: SYSTEM.settings(), queryFn: () => systemApi.getSettings() });
  if (!data) return <Skeleton className="h-64 w-full" />;
  return (
    <div className="grid gap-4">
      <SettingsForm key={JSON.stringify(data)} settings={data} />
      <AiSettingsLink />
    </div>
  );
}

/** Cài đặt Trợ lý chat nằm ở AI → Cài đặt (D23). */
function AiSettingsLink() {
  const t = useT();
  return (
    <Link
      to="/sa/ai-settings"
      data-testid="settings-ai-link"
      className="flex items-center gap-3 rounded-2xl border border-border bg-card p-4 text-sm shadow-card transition-colors hover:bg-accent"
    >
      <Sparkles className="h-5 w-5 shrink-0 text-brand" aria-hidden />
      <span className="min-w-0 flex-1">{t("sa.settings.chatMoved")}</span>
      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
    </Link>
  );
}

function SettingsForm({ settings }: { settings: SystemSettings }) {
  const t = useT();
  const [draft, setDraft] = useState<Draft>(() => toDraft(settings));
  const patch = diff(settings, draft);
  const valid = NUMERIC.every((k) => isUint(draft[k]));
  const dirty = Object.keys(patch).length > 0;
  const isDefault = (k: string) => settings.defaults_applied.includes(k);
  const save = useSaveSettings(patch);

  return (
    <form
      className="grid grid-cols-1 gap-4 xl:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty && valid) save.mutate();
      }}
    >
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="text-base">{t("sa.settings.access")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <Field
            id="ss-signup-mode"
            label={<span className="flex flex-wrap items-center gap-2">{t("sa.settings.signupMode")}<DefaultBadge k="signup_mode" on={isDefault("signup_mode")} /></span>}
            hint={t("sa.settings.signupModeHint")}
          >
            <NativeSelect id="ss-signup-mode" data-testid="settings-signup-mode" value={draft.signup_mode} onChange={(e) => setDraft({ ...draft, signup_mode: e.target.value as SignupMode })}>
              {SIGNUP_MODES.map((m) => (
                <option key={m} value={m}>
                  {t(`sa.settings.signupMode.${m}`)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field
            id="ss-verify"
            label={<span className="flex flex-wrap items-center gap-2">{t("sa.settings.emailVerification")}<DefaultBadge k="email_verification" on={isDefault("email_verification")} /></span>}
          >
            <NativeSelect id="ss-verify" data-testid="settings-email-verification" value={draft.email_verification} onChange={(e) => setDraft({ ...draft, email_verification: e.target.value as VerifyMode })}>
              {VERIFY_MODES.map((m) => (
                <option key={m} value={m}>
                  {t(`sa.settings.emailVerification.${m}`)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <ToggleRow
            id="ss-google"
            testId="settings-google"
            label={<span className="flex flex-wrap items-center gap-2">{t("sa.settings.google")}<DefaultBadge k="google_enabled" on={isDefault("google_enabled")} /></span>}
            hint={settings.google_configured ? t("sa.settings.googleHint") : t("sa.settings.googleMissing")}
            checked={draft.google_enabled}
            disabled={!settings.google_configured && !draft.google_enabled}
            onChange={(v) => setDraft({ ...draft, google_enabled: v })}
          />
        </CardContent>
      </Card>
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="text-base">{t("sa.settings.limits")}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {NUMERIC.map((k) => (
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
        </CardContent>
      </Card>
      <SaveBar disabled={!dirty || !valid || save.isPending} />
    </form>
  );
}
