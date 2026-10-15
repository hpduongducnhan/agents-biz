import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { RBAC } from "@/features/rbac/keys";
import { rbacApi } from "@/features/rbac/api";
import { tenantApi } from "@/features/tenant/api";
import { TENANT } from "@/features/tenant/keys";
import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";
import { Button, Field, FormDialog, Input, NativeSelect, Tabs, TabsList, TabsTrigger } from "@/ui";

type Mode = "email" | "link";

/** Tạo lời mời: qua email (gửi thư, dùng 1 lần) hoặc link dùng chung (chép gửi qua chat). Link thô chỉ hiện một lần. */
export function InviteDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>("email");
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [days, setDays] = useState("7");
  const [maxUses, setMaxUses] = useState("20");
  const [link, setLink] = useState<string | null>(null);
  const { data: roles } = useQuery({ queryKey: RBAC.roles(), queryFn: rbacApi.listRoles, enabled: open });
  const create = useMutation({
    mutationFn: () =>
      tenantApi.invite({
        email: mode === "email" ? email.trim() : null,
        role_id: roleId || null,
        days: Number(days),
        max_uses: mode === "link" ? Number(maxUses) : null,
      }),
    onSuccess: (out) => {
      void qc.invalidateQueries({ queryKey: TENANT.invites() });
      toast.success(t("invite.created"));
      setLink(out.link ?? null);
    },
  });
  const close = (v: boolean) => {
    onOpenChange(v);
    if (!v) {
      setLink(null);
      setEmail("");
      create.reset();
    }
  };
  const valid = /^\d+$/.test(days) && Number(days) >= 1 && Number(days) <= 30 && (mode === "link" ? /^\d+$/.test(maxUses) && Number(maxUses) >= 1 : email.includes("@"));

  return (
    <FormDialog
      open={open}
      onOpenChange={close}
      title={t("invite.new")}
      onSubmit={() => (link ? close(false) : create.mutate())}
      submitting={create.isPending}
      disabled={!link && !valid}
      submitLabel={link ? t("common.close") : t("invite.create")}
      error={create.error ? errorText(create.error) : undefined}
    >
      {link ? (
        <Field id="inv-link" label={t("invite.linkReady")}>
          <div className="flex gap-2">
            <Input id="inv-link" readOnly value={link} data-testid="invite-link" />
            <Button
              type="button"
              variant="outline"
              aria-label={t("invite.copy")}
              onClick={() => void navigator.clipboard?.writeText(link).then(() => toast.success(t("invite.copied")))}
            >
              <Copy className="h-4 w-4" />
            </Button>
          </div>
        </Field>
      ) : (
        <>
          <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="email" data-testid="invite-mode-email">
                {t("invite.byEmail")}
              </TabsTrigger>
              <TabsTrigger value="link" data-testid="invite-mode-link">
                {t("invite.byLink")}
              </TabsTrigger>
            </TabsList>
          </Tabs>
          {mode === "email" && (
            <Field id="inv-email" label={t("invite.email")}>
              <Input id="inv-email" type="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="invite-email" />
            </Field>
          )}
          <Field id="inv-role" label={t("invite.role")}>
            <NativeSelect id="inv-role" value={roleId} onChange={(e) => setRoleId(e.target.value)} data-testid="invite-role">
              <option value="">member</option>
              {(roles?.items ?? [])
                .filter((r) => r.name !== "member")
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
            </NativeSelect>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field id="inv-days" label={t("invite.days")}>
              <Input id="inv-days" inputMode="numeric" className="num" value={days} onChange={(e) => setDays(e.target.value)} data-testid="invite-days" />
            </Field>
            {mode === "link" && (
              <Field id="inv-max" label={t("invite.maxUses")}>
                <Input id="inv-max" inputMode="numeric" className="num" value={maxUses} onChange={(e) => setMaxUses(e.target.value)} data-testid="invite-max-uses" />
              </Field>
            )}
          </div>
        </>
      )}
    </FormDialog>
  );
}
