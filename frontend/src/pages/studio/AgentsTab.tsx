import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Plus, Wand2 } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { studioApi } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Badge, Button, EmptyState, Skeleton } from "@/ui";

import { AgentEditor } from "./AgentEditor";
import { ConfigureAllDialog } from "./ConfigureAllDialog";
import { HooksPanel } from "./HooksPanel";
import { ItemCard, TabActions } from "./common";
import { KeysPanel } from "./KeysPanel";
import { LimitsPanel } from "./LimitsPanel";
import { RoutesPanel } from "./RoutesPanel";
import { ToolsPanel } from "./ToolsPanel";

/** Danh sách agent (kèm cảnh báo cấu hình) → `?agent=<id|new>` mở trình sửa. */
export function AgentsTab() {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const open = params.get("agent");
  const go = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("agent", id);
    else next.delete("agent");
    setParams(next);
  };
  const { data, isLoading } = useQuery({ queryKey: STUDIO.agents(), queryFn: studioApi.agents });
  const [bulk, setBulk] = useState(false);
  const detail = useQuery({ queryKey: STUDIO.agent(open ?? ""), queryFn: () => studioApi.agent(open!), enabled: !!open && open !== "new" });
  if (open) {
    if (open !== "new" && detail.isLoading) return <Skeleton className="h-64 w-full" />;
    const agent = open === "new" ? null : (detail.data ?? null);
    return (
      <div className="grid gap-4">
        <Button variant="ghost" className="w-fit" onClick={() => go(null)} data-testid="agent-back">
          <ArrowLeft className="h-4 w-4" />
          {t("studio.back")}
        </Button>
        <AgentEditor agent={agent} onSaved={(id) => go(id)} />
        {agent && (
          <>
            {agent.kind === "orchestrator" ? <RoutesPanel agent={agent} /> : null}
            <KeysPanel agent={agent} />
            <LimitsPanel agent={agent} />
            {agent.kind === "orchestrator" ? null : <ToolsPanel agent={agent} />}
            <HooksPanel agent={agent} />
          </>
        )}
      </div>
    );
  }
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="grid gap-3">
      <TabActions>
        <Button variant="outline" onClick={() => setBulk(true)} data-testid="agent-configure-all">
          <Wand2 className="h-4 w-4" />
          {t("studio.configureAll")}
        </Button>
        <Button onClick={() => go("new")} data-testid="agent-add">
          <Plus className="h-4 w-4" />
          {t("studio.newAgent")}
        </Button>
      </TabActions>
      {bulk && <ConfigureAllDialog onClose={() => setBulk(false)} />}
      {!data?.length ? (
        <EmptyState title={t("studio.empty")} />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {data.map((a) => (
            <ItemCard
              key={a.id}
              testId={`agent-${a.slug}`}
              title={a.name}
              badges={
                <>
                  <Badge variant="secondary">{t(`studio.kind.${a.kind}`)}</Badge>
                  {!a.is_active && <Badge variant="outline">{t("studio.status.disabled")}</Badge>}
                  {a.warnings.map((w) => (
                    <Badge key={w} variant="destructive" data-testid={`agent-warning-${w}`}>
                      {t(`studio.warning.${w}`)}
                    </Badge>
                  ))}
                </>
              }
              meta={`${a.slug} · ${a.model_name ?? t("studio.noModel")} · ${a.toolsets.join(", ") || "—"}`}
              actions={
                <Button size="sm" variant="outline" onClick={() => go(a.id)} data-testid={`agent-open-${a.slug}`}>
                  {t("studio.edit")}
                </Button>
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}
