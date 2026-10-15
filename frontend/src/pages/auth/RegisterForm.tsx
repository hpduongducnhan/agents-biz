import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router";
import { z } from "zod";

import { authApi } from "@/features/auth/api";
import { useAuthStore } from "@/lib/auth/store";
import { type TFn, useT } from "@/lib/i18n";
import { Button, Field, Input } from "@/ui";

import { type FormError, formErrorOf } from "./auth-error";
import { FormAlert } from "./FormAlert";

const schema = (t: TFn) =>
  z.object({
    name: z.string().trim().min(1, t("auth.err.nameRequired")).max(200),
    email: z.email(t("auth.err.email")),
    password: z.string().min(8, t("err.2107")),
    tenant_name: z.string().trim().max(200),
  });
type RegisterValues = z.infer<ReturnType<typeof schema>>;

type Props = {
  next: string;
  /** Lời mời (D12): vào đúng tổ chức + vai trò của lời mời, bỏ qua `signup_mode`. */
  inviteToken?: string;
  /** `signup_mode=new_tenant` và không có lời mời → hỏi tên tổ chức mới. */
  askTenant?: boolean;
};

/** Form đăng ký dùng chung cho trang Đăng ký và trang Nhận lời mời. `email_verification=required` → chưa có phiên,
 *  hiện hướng dẫn mở thư xác thực (D14). */
export function RegisterForm({ next, inviteToken, askTenant = false }: Props) {
  const t = useT();
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const [error, setError] = useState<FormError | null>(null);
  const [checkEmail, setCheckEmail] = useState<string | null>(null);
  const form = useForm<RegisterValues>({
    resolver: zodResolver(schema(t)),
    defaultValues: { name: "", email: "", password: "", tenant_name: "" },
  });
  const errors = form.formState.errors;

  const onSubmit = async (d: RegisterValues) => {
    setError(null);
    try {
      const res = await authApi.register({
        name: d.name.trim(),
        email: d.email.trim(),
        password: d.password,
        invite_token: inviteToken ?? null,
        tenant_name: askTenant && d.tenant_name.trim() ? d.tenant_name.trim() : null,
      });
      if (!res.tokens) {
        setCheckEmail(res.user.email);
        return;
      }
      login(res.tokens, res.user);
      void navigate(next, { replace: true });
    } catch (err) {
      setError(formErrorOf(err));
    }
  };

  if (checkEmail)
    return (
      <div role="status" data-testid="register-check-email" className="space-y-3 rounded-xl border border-border bg-card p-4 text-center">
        <MailCheck className="mx-auto h-8 w-8 text-brand" aria-hidden />
        <h2 className="font-extrabold">{t("auth.register.checkEmail.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("auth.register.checkEmail.body", { email: checkEmail })}</p>
        <Link to="/login" className="inline-block font-bold text-brand">
          {t("auth.toLogin")}
        </Link>
      </div>
    );

  return (
    <>
      {error && <FormAlert text={error.text} cid={error.cid} />}
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field id="r-name" label={t("auth.field.fullName")} error={errors.name?.message}>
          <Input id="r-name" autoComplete="name" maxLength={200} data-testid="register-name" {...form.register("name")} />
        </Field>
        <Field id="r-email" label={t("auth.field.email")} error={errors.email?.message}>
          <Input id="r-email" type="email" inputMode="email" autoComplete="email" data-testid="register-email" {...form.register("email")} />
        </Field>
        <Field id="r-password" label={t("auth.field.password")} error={errors.password?.message} hint={t("auth.register.passwordHint")}>
          <Input id="r-password" type="password" autoComplete="new-password" data-testid="register-password" {...form.register("password")} />
        </Field>
        {askTenant && (
          <Field id="r-tenant" label={t("auth.register.tenantName")} hint={t("auth.register.tenantNameHint")}>
            <Input id="r-tenant" maxLength={200} autoComplete="organization" data-testid="register-tenant" {...form.register("tenant_name")} />
          </Field>
        )}
        <Button type="submit" size="lg" className="w-full" disabled={form.formState.isSubmitting} data-testid="register-submit">
          {t("auth.register.submit")}
        </Button>
      </form>
    </>
  );
}
