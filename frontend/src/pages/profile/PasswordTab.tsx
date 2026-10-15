import { useMutation } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { authApi } from "@/features/auth/api";
import { setTokens } from "@/lib/auth-tokens";
import { useAuthStore } from "@/lib/auth/store";
import type { Me } from "@/lib/auth/types";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { type FormError, formErrorOf } from "@/pages/auth/auth-error";
import { FormAlert } from "@/pages/auth/FormAlert";
import { Button, Card, CardContent, ConfirmDialog, Field, Input } from "@/ui";

const EMPTY = { current: "", next: "", confirm: "" };

export function PasswordTab({ user, forced }: { user: Me; forced: boolean }) {
  const t = useT();
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const [pw, setPw] = useState(EMPTY);
  const [error, setError] = useState<FormError | null>(null);
  const change = useMutation({
    mutationFn: async () => {
      const tokens = await authApi.changePassword({ current_password: user.has_password ? pw.current : "", new_password: pw.next });
      setTokens(tokens.access_token, tokens.refresh_token); // mọi phiên cũ đã bị thu hồi — tải `me` bằng phiên mới
      return { tokens, me: await authApi.me() };
    },
    onSuccess: ({ tokens, me }) => {
      login(tokens, me);
      setPw(EMPTY);
      toast.success(t("profile.passwordChanged"));
      if (forced) void navigate("/", { replace: true });
    },
    onError: (err) => setError(formErrorOf(err)),
  });

  const submit = () => {
    setError(null);
    if (pw.next.length < 8) return setError({ text: t("err.2107"), cid: null });
    if (pw.next !== pw.confirm) return setError({ text: t("profile.mismatch"), cid: null });
    change.mutate();
  };

  return (
    <Card className="shadow-card">
      <CardContent className="p-5">
        <form
          className="grid max-w-xl grid-cols-1 gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {!user.has_password && <p className="text-sm text-muted-foreground">{t("profile.googleOnly")}</p>}
          {error && <FormAlert text={error.text} cid={error.cid} />}
          {user.has_password && (
            <Field id="pw-current" label={t("profile.current")}>
              <Input id="pw-current" type="password" autoComplete="current-password" data-testid="pw-current" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
            </Field>
          )}
          <Field id="pw-new" label={t("profile.new")} hint={t("auth.register.passwordHint")}>
            <Input id="pw-new" type="password" autoComplete="new-password" data-testid="pw-new" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          </Field>
          <Field id="pw-confirm" label={t("profile.confirm")}>
            <Input id="pw-confirm" type="password" autoComplete="new-password" data-testid="pw-confirm" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
          </Field>
          <div className="flex justify-end">
            <Button type="submit" disabled={change.isPending} data-testid="change-password">
              {t("profile.changePassword")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function SessionsCard() {
  const t = useT();
  const navigate = useNavigate();
  const logout = useAuthStore((s) => s.logout);
  const [confirm, setConfirm] = useState(false);
  const logoutAll = useMutation({
    mutationFn: () => authApi.logoutAll(),
    onSuccess: () => {
      logout();
      void navigate("/login", { replace: true });
    },
    onError: (err) => toastError(err),
  });
  return (
    <Card className="shadow-card">
      <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="min-w-0">
          <div className="text-sm font-bold">{t("profile.sessions")}</div>
          <div className="text-sm text-muted-foreground">{t("profile.logoutAllDesc")}</div>
        </div>
        <Button variant="outline" onClick={() => setConfirm(true)} data-testid="logout-all">
          <LogOut className="h-4 w-4" />
          {t("profile.logoutAll")}
        </Button>
      </CardContent>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("profile.logoutAll")}
        description={t("profile.logoutAllDesc")}
        onConfirm={() => logoutAll.mutate()}
        loading={logoutAll.isPending}
      />
    </Card>
  );
}
