import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { adminApi } from "@/features/admin/api";
import { ADMIN } from "@/features/admin/keys";
import { guardApi } from "@/features/agent/guardApi";
import { STUDIO } from "@/features/agent/keys";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { errorText } from "@/lib/query-client";
import { Field, FormDialog, Input, Label, NativeSelect, Textarea } from "@/ui";

const DURATIONS = ["15", "60", "1440", "10080", "open"] as const;

/** Superadmin chặn một user khỏi trợ lý: tìm user, chọn thời gian (hoặc tới khi mở), lý do bắt buộc. */
export function BlockChatDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [userId, setUserId] = useState<string | null>(null);
  const [duration, setDuration] = useState<(typeof DURATIONS)[number]>("60");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const q = { q: query.trim() || undefined, is_active: true, limit: 10, offset: 0 };
  const { data } = useQuery({ queryKey: ADMIN.users(q), queryFn: () => adminApi.listUsers(q) });
  const users = (data?.items ?? []).filter((u) => !u.is_superadmin);
  const picked = users.find((u) => u.id === userId);
  const save = useMutation({
    mutationFn: () => guardApi.block({ user_id: userId!, minutes: duration === "open" ? null : Number(duration), reason: reason.trim() }),
    onSuccess: (b) => {
      toast.success(t("guard.blocked", { name: b.user.name }));
      void qc.invalidateQueries({ queryKey: STUDIO.chatBlocks() });
      onClose();
    },
    onError: (err) => setError(errorText(err)),
  });

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t("guard.blockUser")}
      submitLabel={t("guard.blockUser")}
      onSubmit={() => save.mutate()}
      submitting={save.isPending}
      disabled={!userId || !reason.trim()}
      error={error}
    >
      <Field id="bc-search" label={t("guard.pickUser")}>
        <Input id="bc-search" data-testid="guard-search" value={query} placeholder={t("guard.search")} onChange={(e) => setQuery(e.target.value)} />
      </Field>
      <ul className="grid max-h-56 gap-1 overflow-y-auto rounded-xl border border-border p-1" data-testid="guard-users">
        {users.map((u) => (
          <li key={u.id}>
            <button
              type="button"
              data-testid={`guard-pick-${u.id}`}
              aria-pressed={u.id === userId}
              onClick={() => setUserId(u.id)}
              className={cn("grid w-full min-w-0 rounded-lg px-3 py-2 text-left hover:bg-accent", u.id === userId && "bg-brand-muted")}
            >
              <span className="truncate font-semibold">{u.name}</span>
              <span className="truncate text-xs text-muted-foreground">{u.email}</span>
            </button>
          </li>
        ))}
      </ul>
      {picked ? <p className="text-sm">{picked.email}</p> : null}
      <div className="grid gap-1.5">
        <Label htmlFor="bc-duration">{t("guard.duration")}</Label>
        <NativeSelect id="bc-duration" data-testid="guard-duration" value={duration} onChange={(e) => setDuration(e.target.value as (typeof DURATIONS)[number])}>
          {DURATIONS.map((d) => (
            <option key={d} value={d}>
              {t(`guard.dur.${d}`)}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="bc-reason">{t("guard.reason")}</Label>
        <Textarea id="bc-reason" data-testid="guard-reason" rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
    </FormDialog>
  );
}
