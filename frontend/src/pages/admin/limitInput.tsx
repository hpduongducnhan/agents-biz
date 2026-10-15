import type { SystemSettings } from "@/features/system/api";
import { useT } from "@/lib/i18n";
import { Field, Input } from "@/ui";

/** Ô hạn mức chat: để trống = không đặt (null, theo tầng dưới), hoặc số nguyên trong khoảng cho phép. */
export const CHAT_KEYS = ["chat_per_minute", "chat_per_hour", "chat_per_day"] as const;
const MAX = { chat_per_minute: 100_000, chat_per_hour: 100_000, chat_per_day: 100_000 } as const;
export type LimitKey = keyof typeof MAX;
export type LimitDraft = Record<LimitKey, string>;
type Policies = Partial<Record<LimitKey, number | null>>;
const KEYS = Object.keys(MAX) as LimitKey[];

export const limitText = (v: number | null | undefined): string => (v == null ? "" : String(v));

export function parseLimit(text: string, max = 1000): { ok: boolean; value: number | null } {
  const v = text.trim();
  if (!v) return { ok: true, value: null };
  if (!/^\d+$/.test(v) || Number(v) > max) return { ok: false, value: null };
  return { ok: true, value: Number(v) };
}

export const limitDraft = (p: Policies | undefined): LimitDraft => Object.fromEntries(KEYS.map((k) => [k, limitText(p?.[k])])) as LimitDraft;
export const limitPolicies = (d: LimitDraft) => Object.fromEntries(KEYS.map((k) => [k, parseLimit(d[k], MAX[k]).value])) as Record<LimitKey, number | null>;
export const limitsValid = (d: LimitDraft) => KEYS.every((k) => parseLimit(d[k], MAX[k]).ok);
export const limitsChanged = (d: LimitDraft, p: Policies | undefined) => KEYS.some((k) => parseLimit(d[k], MAX[k]).value !== (p?.[k] ?? null));

/** Giá trị mặc định hệ thống cho dòng gợi ý "để trống = mặc định (n)". */
export const limitDefaults = (s: SystemSettings | undefined): Record<LimitKey, number> | null =>
  s ? { chat_per_minute: s.chat_per_minute, chat_per_hour: s.chat_per_hour, chat_per_day: s.chat_per_day } : null;

type Props = {
  idPrefix: string;
  testPrefix: string;
  draft: LimitDraft;
  defaults: Record<LimitKey, number> | null;
  onChange: (d: LimitDraft) => void;
  disabled?: boolean;
};

/** 3 ô tin chat / phút · giờ · ngày; test id `<prefix>-chat_per_*`. */
export function LimitFields({ idPrefix, testPrefix, draft, defaults, onChange, disabled }: Props) {
  const t = useT();
  const input = (k: LimitKey, testId: string) => (
    <Input
      id={`${idPrefix}-${k}`}
      data-testid={testId}
      inputMode="numeric"
      className="num"
      value={draft[k]}
      disabled={disabled}
      onChange={(e) => onChange({ ...draft, [k]: e.target.value })}
    />
  );
  const err = (k: LimitKey) => (parseLimit(draft[k], MAX[k]).ok ? undefined : t("limits.invalid"));
  return (
    <>
      <fieldset className="grid gap-2 rounded-xl border border-border p-3" data-testid={`${testPrefix}-chat-limits`}>
        <legend className="px-1 text-sm font-semibold">{t("limits.chat")}</legend>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {CHAT_KEYS.map((k) => (
            <Field key={k} id={`${idPrefix}-${k}`} label={t(`guard.field.${k}`)} hint={t("limits.chatUnset", { n: defaults?.[k] ?? "…" })} error={err(k)}>
              {input(k, `${testPrefix}-${k}`)}
            </Field>
          ))}
        </div>
      </fieldset>
    </>
  );
}
