import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { authApi } from "@/features/auth/api";
import { AUTH } from "@/features/auth/keys";
import { useAuthStore } from "@/lib/auth/store";
import { useT } from "@/lib/i18n";

import { AuthLayout } from "./AuthLayout";
import { type FormError, formErrorOf } from "./auth-error";
import { FormAlert } from "./FormAlert";

/** `/verify-email?token=…` — gọi xác thực một lần khi mở trang (D14). */
export default function VerifyEmailPage() {
  const t = useT();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const signedIn = useAuthStore((s) => !!s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [state, setState] = useState<"working" | "done" | "error">("working");
  const [error, setError] = useState<FormError | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // StrictMode gọi effect hai lần — token chỉ dùng được một lần
    started.current = true;
    authApi
      .verifyEmail(token)
      .then(() => {
        setState("done");
        const current = useAuthStore.getState().user;
        if (current) setUser({ ...current, email_verified: true }); // banner nhắc xác thực tắt ngay
        void qc.invalidateQueries({ queryKey: AUTH.me() });
      })
      .catch((err: unknown) => {
        setError(formErrorOf(err));
        setState("error");
      });
  }, [token, qc, setUser]);

  return (
    <AuthLayout title={t("auth.verify.title")} subtitle={state === "working" ? t("auth.verify.working") : ""}>
      {state === "done" && (
        <p role="status" data-testid="verify-done" className="rounded-xl bg-brand-muted p-3 text-sm">
          {t("auth.verify.done")}
        </p>
      )}
      {state === "error" && error && <FormAlert text={error.text} cid={error.cid} />}
      <Link to={signedIn ? "/" : "/login"} className="block text-center text-sm font-bold text-brand">
        {signedIn ? t("page.home") : t("auth.toLogin")}
      </Link>
    </AuthLayout>
  );
}
