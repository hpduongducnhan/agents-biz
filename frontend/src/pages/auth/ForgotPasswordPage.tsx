import { useState } from "react";
import { Link } from "react-router";

import { authApi } from "@/features/auth/api";
import { useT } from "@/lib/i18n";
import { Button, Field, Input } from "@/ui";

import { AuthLayout } from "./AuthLayout";
import { type FormError, formErrorOf } from "./auth-error";
import { FormAlert } from "./FormAlert";

/** `/forgot-password` — luôn báo "đã gửi nếu có tài khoản" (backend không lộ email có tồn tại không — D14). */
export default function ForgotPasswordPage() {
  const t = useT();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FormError | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await authApi.forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      setError(formErrorOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title={t("auth.forgot.title")} subtitle={t("auth.forgot.subtitle")}>
      {error && <FormAlert text={error.text} cid={error.cid} />}
      {sent ? (
        <p role="status" data-testid="forgot-sent" className="rounded-xl bg-brand-muted p-3 text-sm">
          {t("auth.forgot.sent")}
        </p>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field id="f-email" label={t("auth.field.email")}>
            <Input id="f-email" type="email" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="forgot-email" />
          </Field>
          <Button type="submit" size="lg" className="w-full" disabled={busy || !email.includes("@")} data-testid="forgot-submit">
            {t("auth.forgot.submit")}
          </Button>
        </form>
      )}
      <Link to="/login" className="block text-center text-sm font-bold text-brand">
        {t("auth.toLogin")}
      </Link>
    </AuthLayout>
  );
}
