import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { authApi } from "@/features/auth/api";
import { useT } from "@/lib/i18n";
import { Button, Field, Input } from "@/ui";

import { AuthLayout } from "./AuthLayout";
import { type FormError, formErrorOf } from "./auth-error";
import { FormAlert } from "./FormAlert";

/** `/reset-password?token=…` — đặt mật khẩu mới bằng link trong thư (dùng một lần, mọi phiên cũ bị thu hồi). */
export default function ResetPasswordPage() {
  const t = useT();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FormError | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await authApi.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(formErrorOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title={t("auth.reset.title")} subtitle={t("auth.reset.subtitle")}>
      {error && <FormAlert text={error.text} cid={error.cid} />}
      {done ? (
        <p role="status" data-testid="reset-done" className="rounded-xl bg-brand-muted p-3 text-sm">
          {t("auth.reset.done")}
        </p>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field id="rp-password" label={t("auth.field.password")} hint={t("auth.register.passwordHint")}>
            <Input id="rp-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} data-testid="reset-password" />
          </Field>
          <Button type="submit" size="lg" className="w-full" disabled={busy || !token || password.length < 8} data-testid="reset-submit">
            {t("auth.reset.submit")}
          </Button>
        </form>
      )}
      <Link to="/login" className="block text-center text-sm font-bold text-brand">
        {t("auth.toLogin")}
      </Link>
    </AuthLayout>
  );
}
