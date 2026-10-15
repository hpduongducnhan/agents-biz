import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { adminApi, type AdminUser } from "@/features/admin/api";
import { ADMIN } from "@/features/admin/keys";
import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";
import { Field, FormDialog, Input } from "@/ui";

export function ResetPasswordDialog({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const reset = useMutation({
    mutationFn: () => adminApi.resetPassword({ user_id: user.id, new_password: pw }),
    onSuccess: () => {
      toast.success(t("admin.users.resetDone", { email: user.email }));
      void qc.invalidateQueries({ queryKey: ADMIN.all });
      onClose();
    },
    onError: (err) => setError(errorText(err)),
  });
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={t("admin.users.reset")} onSubmit={() => reset.mutate()} submitting={reset.isPending} disabled={pw.length < 8} error={error}>
      <p className="break-all text-sm text-muted-foreground">{user.email}</p>
      <Field id="rp-password" label={t("profile.new")} hint={t("admin.users.resetHint")}>
        <Input id="rp-password" type="text" autoComplete="off" data-testid="user-reset-password" value={pw} onChange={(e) => setPw(e.target.value)} />
      </Field>
    </FormDialog>
  );
}
