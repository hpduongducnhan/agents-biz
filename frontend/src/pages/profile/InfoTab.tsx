import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { authApi } from "@/features/auth/api";
import { AUTH } from "@/features/auth/keys";
import { LOCALES } from "@/layout/Toggles";
import { useAuthStore } from "@/lib/auth/store";
import type { Me } from "@/lib/auth/types";
import { type TFn, useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Button, Card, CardContent, Field, Input, NativeSelect } from "@/ui";

const TIMEZONES = [
  "Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Singapore", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul",
  "Australia/Sydney", "Europe/London", "Europe/Paris", "America/New_York", "America/Los_Angeles", "UTC",
];

const schema = (t: TFn) =>
  z.object({
    name: z.string().trim().min(1, t("auth.err.nameRequired")).max(200),
    timezone: z.string().min(1),
    locale: z.enum(["vi", "en"]),
  });
type InfoForm = z.infer<ReturnType<typeof schema>>;

export function InfoTab({ user }: { user: Me }) {
  const t = useT();
  const qc = useQueryClient();
  const setUser = useAuthStore((s) => s.setUser);
  const form = useForm<InfoForm>({
    resolver: zodResolver(schema(t)),
    defaultValues: { name: user.name, timezone: user.timezone, locale: user.locale === "en" ? "en" : "vi" },
  });
  const save = useMutation({
    mutationFn: (d: InfoForm) => authApi.updateMe({ name: d.name.trim(), timezone: d.timezone, locale: d.locale }),
    onSuccess: (next) => {
      setUser(next);
      qc.setQueryData(AUTH.me(), next);
      toast.success(t("profile.saved"));
    },
    onError: (err) => toastError(err),
  });
  const zones = TIMEZONES.includes(user.timezone) ? TIMEZONES : [user.timezone, ...TIMEZONES];
  const errors = form.formState.errors;

  return (
    <Card className="shadow-card">
      <CardContent className="p-5">
        <form className="grid grid-cols-1 gap-4 md:grid-cols-2" onSubmit={form.handleSubmit((d) => save.mutate(d))} noValidate>
          <Field id="p-email" label={t("auth.field.email")}>
            <Input id="p-email" value={user.email} disabled />
          </Field>
          <Field id="p-name" label={t("auth.field.fullName")} error={errors.name?.message}>
            <Input id="p-name" maxLength={200} data-testid="profile-name" {...form.register("name")} />
          </Field>
          <Field id="p-tz" label={t("profile.timezone")}>
            <NativeSelect id="p-tz" data-testid="profile-timezone" {...form.register("timezone")}>
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id="p-locale" label={t("profile.locale")}>
            <NativeSelect id="p-locale" data-testid="profile-locale" {...form.register("locale")}>
              {LOCALES.map((l) => (
                <option key={l} value={l}>
                  {t(`lang.${l}`)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <div className="flex justify-end md:col-span-2">
            <Button type="submit" disabled={save.isPending} data-testid="profile-save">
              {t("common.save")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
