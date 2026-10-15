import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { type Hook, studioApi, type StudioAgent } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmDialog } from "@/ui";

import { ItemCard, useStudioMutation } from "./common";
import { HookDialog } from "./HookDialog";

export function HooksPanel({ agent }: { agent: StudioAgent }) {
  const t = useT();
  const { data } = useQuery({ queryKey: STUDIO.hooks(agent.id), queryFn: () => studioApi.hooks(agent.id) });
  const [editing, setEditing] = useState<Hook | "new" | null>(null);
  const [deleting, setDeleting] = useState<Hook | null>(null);
  const remove = useStudioMutation((id: string) => studioApi.deleteHook(id), [STUDIO.hooks(agent.id), STUDIO.agent(agent.id)], () => setDeleting(null));
  return (
    <Card data-testid="hooks-panel">
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>{t("studio.section.hooks")}</CardTitle>
        <Button size="sm" onClick={() => setEditing("new")} data-testid="hook-add">
          <Plus className="h-4 w-4" />
          {t("studio.hook.add")}
        </Button>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-2">
          {(data ?? []).map((h) => (
            <ItemCard
              key={h.id}
              testId={`hook-${h.id}`}
              title={h.name || h.action}
              badges={
                <>
                  <Badge variant="secondary">{h.point}</Badge>
                  <Badge variant="outline">{h.action}</Badge>
                  {!h.enabled && <Badge variant="outline">{t("studio.status.disabled")}</Badge>}
                </>
              }
              meta={(h.conditions as { path: string; op: string; value?: unknown }[]).map((c) => `${c.path} ${c.op} ${JSON.stringify(c.value ?? "")}`).join(" · ") || "—"}
              actions={
                <>
                  <Button size="sm" variant="outline" onClick={() => setEditing(h)}>
                    {t("studio.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setDeleting(h)}>
                    {t("studio.delete")}
                  </Button>
                </>
              }
            />
          ))}
        </ul>
      </CardContent>
      {editing && <HookDialog agentId={agent.id} hook={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("studio.delete")}
        description={t("studio.deleteConfirm", { name: deleting?.name || deleting?.action || "" })}
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </Card>
  );
}
