import { useMutation } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { notificationsApi } from "@/features/notifications/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { type FormError, formErrorOf } from "@/pages/auth/auth-error";
import { FormAlert } from "@/pages/auth/FormAlert";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, Textarea } from "@/ui";

/** Gửi thông báo thử (`notifications.send_test`) — kiểm inbox + realtime tới đúng người (E2E dùng). */
export function SendTestCard({ className }: { className?: string }) {
  const t = useT();
  const [form, setForm] = useState({ email: "", title: "", body: "" });
  const [error, setError] = useState<FormError | null>(null);
  const email = form.email.trim();
  const title = form.title.trim();
  const ok = email.includes("@") && title.length > 0 && title.length <= 200;
  const send = useMutation({
    mutationFn: () => notificationsApi.sendTest({ email, title, body: form.body }),
    onSuccess: () => {
      toast.success(t("sa.test.sent", { email }));
      setForm((f) => ({ ...f, title: "", body: "" }));
      setError(null);
    },
    onError: (err) => setError(formErrorOf(err)),
  });
  return (
    <Card className={cn("shadow-card", className)} data-testid="send-test-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Send className="h-4 w-4 text-brand" />
          {t("sa.test.title")}
        </CardTitle>
        <CardDescription>{t("sa.test.desc")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid grid-cols-1 gap-4 md:grid-cols-2"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (ok) send.mutate();
          }}
        >
          {error && (
            <div className="md:col-span-2">
              <FormAlert text={error.text} cid={error.cid} />
            </div>
          )}
          <Field id="st-email" label={t("auth.field.email")}>
            <Input id="st-email" type="email" inputMode="email" data-testid="send-test-email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field id="st-title" label={t("sa.test.titleField")}>
            <Input id="st-title" maxLength={200} data-testid="send-test-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <div className="md:col-span-2">
            <Field id="st-body" label={t("sa.test.body")}>
              <Textarea id="st-body" rows={2} maxLength={2000} data-testid="send-test-body" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
            </Field>
          </div>
          <div className="flex justify-end md:col-span-2">
            <Button type="submit" disabled={!ok || send.isPending} data-testid="send-test-submit">
              {t("sa.test.send")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
