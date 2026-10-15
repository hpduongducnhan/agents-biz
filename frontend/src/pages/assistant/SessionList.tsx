import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, MoreHorizontal } from "lucide-react";
import { useState } from "react";

import { agentApi, type ChatSession } from "@/features/agent/api";
import { AGENT } from "@/features/agent/keys";
import { cn } from "@/lib/cn";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import {
  Button,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  FormDialog,
  Input,
  Label,
  Skeleton,
} from "@/ui";

const LIST = { limit: 50 };

type Props = { sessionId: string | null; onSelect: (id: string | null) => void };

/** Phiên chat của tôi (mới nhất trước) + tạo mới / đổi tên / xoá. Điện thoại: nằm trong sheet. */
export function SessionList({ sessionId, onSelect }: Props) {
  const t = useT();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: AGENT.sessions(LIST), queryFn: () => agentApi.sessions(LIST) });
  const [renaming, setRenaming] = useState<ChatSession | null>(null);
  const [title, setTitle] = useState("");
  const [deleting, setDeleting] = useState<ChatSession | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: AGENT.sessions() });
  const rename = useMutation({
    mutationFn: () => agentApi.rename(renaming!.id, title.trim()),
    onSuccess: async () => {
      setRenaming(null);
      await refresh();
    },
    onError: toastError,
  });
  const remove = useMutation({
    mutationFn: (id: string) => agentApi.remove(id),
    onSuccess: async (_, id) => {
      setDeleting(null);
      if (id === sessionId) onSelect(null);
      await refresh();
    },
    onError: toastError,
  });
  const items = data?.items ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2" data-testid="session-list">
      <Button variant="outline" className="shrink-0 justify-start" onClick={() => onSelect(null)} data-testid="chat-new">
        <MessageSquarePlus className="h-4 w-4" />
        {t("chat.newChat")}
      </Button>
      {isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : !items.length ? (
        <p className="px-2 py-4 text-sm text-muted-foreground">{t("chat.noSessions")}</p>
      ) : (
        <ul className="grid min-h-0 flex-1 content-start gap-1 overflow-y-auto overscroll-contain">
          {items.map((s) => (
            <li key={s.id} className="flex min-w-0 items-center gap-1">
              <button
                type="button"
                onClick={() => onSelect(s.id)}
                aria-current={s.id === sessionId ? "true" : undefined}
                data-testid={`session-${s.id}`}
                className={cn(
                  "grid min-h-11 min-w-0 flex-1 rounded-xl px-3 py-2 text-left",
                  s.id === sessionId ? "bg-brand-muted font-semibold" : "hover:bg-accent",
                )}
              >
                <span className="block truncate text-sm">{s.title || t("chat.newChat")}</span>
                <span className="text-xs text-muted-foreground">{fmt(s.updated_at, "relative")}</span>
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label={t("chat.rename")} data-testid={`session-menu-${s.id}`}>
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() => {
                      setRenaming(s);
                      setTitle(s.title);
                    }}
                  >
                    {t("chat.rename")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setDeleting(s)} disabled={!!s.open_run_status} className="text-destructive">
                    {t("chat.delete")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </li>
          ))}
        </ul>
      )}
      {renaming && (
        <FormDialog
          open
          onOpenChange={(o) => !o && setRenaming(null)}
          title={t("chat.renameTitle")}
          submitting={rename.isPending}
          disabled={!title.trim()}
          onSubmit={() => rename.mutate()}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="session-title">{t("chat.title")}</Label>
            <Input id="session-title" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
          </div>
        </FormDialog>
      )}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("chat.delete")}
        description={t("chat.deleteConfirm")}
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}
