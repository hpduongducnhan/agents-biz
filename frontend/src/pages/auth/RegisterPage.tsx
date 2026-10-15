import { Link, useSearchParams } from "react-router";

import { usePublicInfo } from "@/features/system/hooks";
import { useT } from "@/lib/i18n";

import { AuthLayout } from "./AuthLayout";
import { safeNext } from "./auth-error";
import { GoogleButton } from "./GoogleButton";
import { RegisterForm } from "./RegisterForm";

export default function RegisterPage() {
  const t = useT();
  const [params] = useSearchParams();
  const { data: info } = usePublicInfo();
  const next = safeNext(params.get("next"));

  return (
    <AuthLayout title={t("auth.register.title")} subtitle={t("auth.register.subtitle")}>
      {info && !info.signup_open && (
        <div role="status" className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-sm">
          {t("auth.register.closed")}
        </div>
      )}
      <RegisterForm next={next} askTenant={info?.signup_mode === "new_tenant"} />
      {info?.google_enabled && <GoogleButton />}
      <p className="text-center text-sm text-muted-foreground">
        {t("auth.register.hasAccount")}{" "}
        <Link to={next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`} className="font-bold text-brand">
          {t("auth.register.toLogin")}
        </Link>
      </p>
    </AuthLayout>
  );
}
