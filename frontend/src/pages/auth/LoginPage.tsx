import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";

import { authApi } from "@/features/auth/api";
import { ApiError } from "@/lib/api";
import { usePublicInfo } from "@/features/system/hooks";
import { useAuthStore } from "@/lib/auth/store";
import { type TFn, useT } from "@/lib/i18n";
import { Button, Field, Input } from "@/ui";

import { AuthLayout } from "./AuthLayout";
import { bannerText, type FormError, formErrorOf, safeNext } from "./auth-error";
import { FormAlert } from "./FormAlert";
import { GoogleButton } from "./GoogleButton";

const schema = (t: TFn) =>
  z.object({ email: z.email(t("auth.err.email")), password: z.string().min(1, t("auth.err.passwordRequired")) });
type LoginForm = z.infer<ReturnType<typeof schema>>;

export default function LoginPage() {
  const t = useT();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const login = useAuthStore((s) => s.login);
  const { data: info } = usePublicInfo();
  const [error, setError] = useState<FormError | null>(null);
  const [unverified, setUnverified] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const form = useForm<LoginForm>({ resolver: zodResolver(schema(t)) });
  const next = safeNext(params.get("next"));
  const banner = bannerText(params);
  const errors = form.formState.errors;

  const onSubmit = async (d: LoginForm) => {
    setError(null);
    setUnverified(null);
    try {
      const res = await authApi.login({ email: d.email.trim(), password: d.password });
      if (!res.tokens) return;
      login(res.tokens, res.user);
      void navigate(next, { replace: true });
    } catch (err) {
      setError(formErrorOf(err));
      if (err instanceof ApiError && err.code === 2113) setUnverified(d.email.trim());
    }
  };

  const resend = async () => {
    if (!unverified) return;
    await authApi.requestVerify(unverified).catch(() => undefined);
    setResent(true);
  };

  return (
    <AuthLayout title={t("auth.login.title")} subtitle={t("auth.login.subtitle")}>
      {banner && <FormAlert text={banner} />}
      {error && <FormAlert text={error.text} cid={error.cid} />}
      {unverified && (
        <Button type="button" variant="outline" className="w-full" onClick={() => void resend()} disabled={resent} data-testid="login-resend-verify">
          {resent ? t("auth.verify.resent") : t("auth.verify.resend")}
        </Button>
      )}
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field id="email" label={t("auth.field.email")} error={errors.email?.message}>
          <Input id="email" type="email" inputMode="email" autoComplete="email" data-testid="login-email" {...form.register("email")} />
        </Field>
        <Field id="password" label={t("auth.field.password")} error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" data-testid="login-password" {...form.register("password")} />
        </Field>
        <Link to="/forgot-password" className="-mt-2 block text-right text-sm font-semibold text-brand" data-testid="login-forgot">
          {t("auth.login.forgot")}
        </Link>
        <Button type="submit" size="lg" className="w-full" disabled={form.formState.isSubmitting} data-testid="login-submit">
          {form.formState.isSubmitting ? t("auth.login.submitting") : t("auth.login.submit")}
        </Button>
      </form>
      {info?.google_enabled && <GoogleButton />}
      <p className="text-center text-sm text-muted-foreground">
        {t("auth.login.noAccount")}{" "}
        <Link to={next === "/" ? "/register" : `/register?next=${encodeURIComponent(next)}`} className="font-bold text-brand">
          {t("auth.login.toRegister")}
        </Link>
      </p>
    </AuthLayout>
  );
}
