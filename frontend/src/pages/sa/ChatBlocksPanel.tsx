import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { type ChatBlock, guardApi } from "@/features/agent/guardApi";
import { STUDIO } from "@/features/agent/keys";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { useIsDesktop } from "@/lib/use-media";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Cell, EmptyState, Row, Skeleton, Table, Tabs, TabsContent, TabsList, TabsTrigger, TruncText } from "@/ui";

import { BlockChatDialog } from "./BlockChatDialog";

const PAGE = { limit: 50, offset: 0 } as const;

/** Đang bị chặn + lịch sử chặn trợ lý; Chặn user / Mở chặn — realtime qua `studio.chat_blocks` (R18). */
export function ChatBlocksPanel() {
  const t = useT();
  const [blocking, setBlocking] = useState(false);
  return (
    <Card className="shadow-card">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">{t("guard.active")}</CardTitle>
        <Button size="sm" data-testid="guard-block-user" onClick={() => setBlocking(true)}>
          <Ban className="h-4 w-4" />
          {t("guard.blockUser")}
        </Button>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="active">
          <TabsList>
            <TabsTrigger value="active" data-testid="guard-tab-active">
              {t("guard.active")}
            </TabsTrigger>
            <TabsTrigger value="history" data-testid="guard-tab-history">
              {t("guard.history")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="active" className="pt-3">
            <BlockList activeOnly />
          </TabsContent>
          <TabsContent value="history" className="pt-3">
            <BlockList activeOnly={false} />
          </TabsContent>
        </Tabs>
      </CardContent>
      {blocking && <BlockChatDialog onClose={() => setBlocking(false)} />}
    </Card>
  );
}

function BlockList({ activeOnly }: { activeOnly: boolean }) {
  const t = useT();
  const qc = useQueryClient();
  const desktop = useIsDesktop();
  const q = { ...PAGE, active_only: activeOnly };
  const { data, isLoading } = useQuery({ queryKey: STUDIO.chatBlocks(q), queryFn: () => guardApi.listBlocks(q) });
  const unblock = useMutation({
    mutationFn: (b: ChatBlock) => guardApi.unblock(b.id),
    onSuccess: () => {
      toast.success(t("guard.unblocked"));
      void qc.invalidateQueries({ queryKey: STUDIO.chatBlocks() });
    },
    onError: (err) => toastError(err),
  });
  const items = data?.items ?? [];
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (!items.length) return <EmptyState icon={<ShieldCheck className="h-10 w-10" />} title={t(activeOnly ? "guard.none" : "guard.noHistory")} />;

  const until = (b: ChatBlock) => {
    if (b.lifted_at) return t("guard.lifted");
    if (!b.active) return t("guard.expired");
    return b.until ? fmt(b.until) : t("guard.untilOpen");
  };
  const action = (b: ChatBlock) =>
    b.active ? (
      <Button size="sm" variant="outline" data-testid={`guard-unblock-${b.id}`} disabled={unblock.isPending} onClick={() => unblock.mutate(b)}>
        {t("guard.unblock")}
      </Button>
    ) : null;
  const source = (b: ChatBlock) => <Badge variant={b.source === "auto" ? "secondary" : "outline"}>{t(`guard.source.${b.source}`)}</Badge>;

  return desktop ? (
    <Table head={[t("guard.col.user"), t("guard.col.until"), t("guard.col.source"), t("guard.col.reason"), t("guard.col.by"), ""]}>
      {items.map((b) => (
        <Row key={b.id} testId={`guard-block-${b.id}`}>
          <Cell className="max-w-[220px]">
            <TruncText text={b.user.name} className="font-semibold" />
            <TruncText text={b.user.email} className="text-xs text-muted-foreground" />
          </Cell>
          <Cell className="whitespace-nowrap">{until(b)}</Cell>
          <Cell>{source(b)}</Cell>
          <Cell className="max-w-[320px]">
            <TruncText text={b.reason || "—"} />
          </Cell>
          <Cell className="max-w-[160px]">
            <TruncText text={b.created_by ?? "—"} />
          </Cell>
          <Cell className="w-28 text-right">{action(b)}</Cell>
        </Row>
      ))}
    </Table>
  ) : (
    <ul className="space-y-2">
      {items.map((b) => (
        <li key={b.id} data-testid={`guard-block-${b.id}`} className="grid gap-1 rounded-2xl border border-border bg-card p-3 text-sm">
          <div className="flex min-w-0 items-center justify-between gap-2">
            <span className="min-w-0 truncate font-semibold">{b.user.name}</span>
            {source(b)}
          </div>
          <span className="break-all text-xs text-muted-foreground">{b.user.email}</span>
          <span>
            {t("guard.col.until")}: {until(b)}
          </span>
          {b.reason ? <p className="break-words text-muted-foreground">{b.reason}</p> : null}
          {action(b) ? <div className="flex justify-end">{action(b)}</div> : null}
        </li>
      ))}
    </ul>
  );
}
