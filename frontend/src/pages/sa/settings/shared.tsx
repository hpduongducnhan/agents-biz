import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { type SettingsPatch, systemApi } from "@/features/system/api";
import { SYSTEM } from "@/features/system/keys";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Badge, Button, Field, Input, Label, Switch } from "@/ui";

/** Phần dùng chung của các trang cài đặt hệ thống (`/sa/settings`, `/sa/ai-settings`): cùng op
 *  `system.get_settings` / `system.update_settings`, nhãn "Mặc định", chỉ gửi trường đã đổi. */

export const isUint = (v: string) => /^\d+$/.test(v.trim());
export const inRange = (v: string, min: number, max: number) => isUint(v) && Number(v) >= min && Number(v) <= max;

export function DefaultBadge({ k, on }: { k: string; on: boolean }) {
  const t = useT();
  return on ? (
    <Badge variant="outline" data-testid={`settings-default-${k}`}>
      {t("sa.settings.isDefault")}
    </Badge>
  ) : null;
}

export function ToggleRow(props: { id: string; testId: string; label: ReactNode; hint: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-border p-3">
      <div className="min-w-0 space-y-1">
        <Label htmlFor={props.id}>{props.label}</Label>
        <p className="text-xs text-muted-foreground">{props.hint}</p>
      </div>
      <Switch id={props.id} data-testid={props.testId} checked={props.checked} disabled={props.disabled} onCheckedChange={props.onChange} />
    </div>
  );
}

/** Ô số của một khoá cài đặt (`settings-field-<khoá>`), nhãn kèm "Mặc định". */
export function NumField(props: { k: string; label: string; value: string; error?: string; hint?: string; isDefault: boolean; disabled?: boolean; onChange: (v: string) => void }) {
  return (
    <Field id={`ss-${props.k}`} label={<span className="flex flex-wrap items-center gap-2">{props.label}<DefaultBadge k={props.k} on={props.isDefault} /></span>} error={props.error} hint={props.hint}>
      <Input
        id={`ss-${props.k}`}
        inputMode="numeric"
        className="num"
        data-testid={`settings-field-${props.k}`}
        value={props.value}
        disabled={props.disabled}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </Field>
  );
}

/** Lưu patch cài đặt; xong ghi lại cache trang + làm mới thông tin công khai (công tắc đăng ký / Google). */
export function useSaveSettings(patch: SettingsPatch) {
  const t = useT();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => systemApi.updateSettings(patch),
    onSuccess: (next) => {
      qc.setQueryData(SYSTEM.settings(), next);
      void qc.invalidateQueries({ queryKey: SYSTEM.publicInfo() });
      toast.success(t("sa.settings.saved"));
    },
    onError: (err) => toastError(err),
  });
}

export function SaveBar({ disabled }: { disabled: boolean }) {
  const t = useT();
  return (
    <div className="sticky bottom-0 flex justify-end border-t border-border bg-background/90 py-3 backdrop-blur xl:col-span-2">
      <Button type="submit" disabled={disabled} data-testid="settings-save">
        {t("common.save")}
      </Button>
    </div>
  );
}
