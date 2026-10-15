import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { type Route, studioApi, type StudioAgent } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, ConfirmDialog } from "@/ui";

import { ItemCard, useStudioMutation } from "./common";
import { RouteDialog } from "./RouteDialog";

/** Route của orchestrator: chuyên gia đích + ý định + ví dụ cho router, theo thứ tự. */
export function RoutesPanel({ agent }: { agent: StudioAgent }) {
  const t = useT();
  const { data } = useQuery({ queryKey: STUDIO.routes(agent.id), queryFn: () => studioApi.routes(agent.id) });
  const agents = useQuery({ queryKey: STUDIO.agents(), queryFn: studioApi.agents });
  const [editing, setEditing] = useState<Route | "new" | null>(null);
  const [deleting, setDeleting] = useState<Route | null>(null);
  const keys = [STUDIO.routes(agent.id), STUDIO.agent(agent.id)];
  const remove = useStudioMutation((r: Route) => studioApi.deleteRoute(agent.id, r.agent_id), keys, () => setDeleting(null));
  const specialists = (agents.data ?? []).filter((a) => a.kind === "specialist");
  return (
    <Card data-testid="routes-panel">
      <CardHeader className="flex-row items-start justify-between gap-2">
        <div className="grid gap-1">
          <CardTitle>{t("studio.section.routes")}</CardTitle>
          <CardDescription>{t("studio.routesHint")}</CardDescription>
        </div>
        <Button size="sm" onClick={() => setEditing("new")} data-testid="route-add">
          <Plus className="h-4 w-4" />
          {t("studio.route.add")}
        </Button>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-2">
          {(data ?? []).map((r) => (
            <ItemCard
              key={r.agent_id}
              testId={`route-${r.slug}`}
              title={r.name}
              badges={
                <>
                  <Badge variant="secondary">{r.slug}</Badge>
                  {!r.enabled && <Badge variant="outline">{t("studio.status.disabled")}</Badge>}
                </>
              }
              meta={`#${r.position} · ${r.intent}`}
              actions={
                <>
                  <Button size="sm" variant="outline" onClick={() => setEditing(r)}>
                    {t("studio.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setDeleting(r)}>
                    {t("studio.delete")}
                  </Button>
                </>
              }
            />
          ))}
        </ul>
      </CardContent>
      {editing && <RouteDialog orchestratorId={agent.id} route={editing === "new" ? null : editing} specialists={specialists} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("studio.delete")}
        description={t("studio.deleteConfirm", { name: deleting?.name ?? "" })}
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </Card>
  );
}
