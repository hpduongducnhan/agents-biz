import { useQuery } from "@tanstack/react-query";
import { Inbox } from "lucide-react";

import { mailApi } from "@/features/tenant/api";
import { MAIL } from "@/features/tenant/keys";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { Card, CardContent, EmptyState, Skeleton } from "@/ui";

/** `/sa/mail` — thư transport `console` đã ghi (dev / stack thử, D14); SMTP thật → báo không có hộp thư. */
export default function MailOutboxPage() {
  const t = useT();
  const { data, isLoading } = useQuery({ queryKey: MAIL.outbox(), queryFn: () => mailApi.outbox(), refetchInterval: 5000 });
  if (isLoading || !data) return <Skeleton className="h-48 w-full" />;
  if (!data.enabled)
    return (
      <p role="status" data-testid="mail-disabled" className="rounded-xl bg-muted p-4 text-sm">
        {t("mail.disabled")}
      </p>
    );
  if (data.items.length === 0) return <EmptyState icon={<Inbox className="h-10 w-10" />} title={t("mail.empty")} />;
  return (
    <ul className="space-y-3" data-testid="mail-outbox">
      {data.items.map((m) => (
        <li key={m.id}>
          <Card className="shadow-card">
            <CardContent className="space-y-2 p-4">
              <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
                <p className="min-w-0 break-words font-bold">{m.subject}</p>
                <span className="text-xs text-muted-foreground">{fmt(m.sent_at)}</span>
              </div>
              <p className="text-xs text-muted-foreground">
                {t("mail.to")}: {m.to}
              </p>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/60 p-3 text-xs">{m.text}</pre>
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}
