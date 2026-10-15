import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { useCallback, useRef } from "react";
import { useSearchParams } from "react-router";

import { agentApi } from "@/features/agent/api";
import { AGENT } from "@/features/agent/keys";
import { useAuthStore } from "@/lib/auth/store";
import { useT } from "@/lib/i18n";
import { EmptyState, Skeleton } from "@/ui";

import { DebugAssistant } from "./DebugAssistant";
import { SimpleChat } from "./simple/SimpleChat";
import { type AssistantView, ViewSwitch } from "./ViewSwitch";

const VIEW_KEY = "bw.assistant.view";

function storedView(): AssistantView | null {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    return v === "debug" || v === "simple" ? v : null;
  } catch {
    return null;
  }
}

function storeView(v: AssistantView) {
  try {
    localStorage.setItem(VIEW_KEY, v);
  } catch {
    /* trình duyệt chặn lưu — chỉ mất lựa chọn đã nhớ */
  }
}

/** Trợ lý (D23 tab cuối). User: màn đơn giản. Superadmin: công tắc Đơn giản ↔ Gỡ lỗi — `?view=` thắng lựa chọn đã
 *  nhớ; chuyển sang Gỡ lỗi mở đúng phiên đang xem ở màn đơn giản. */
export default function AssistantPage() {
  const t = useT();
  const sup = useAuthStore((s) => !!s.user?.is_superadmin);
  const tenantOff = useAuthStore((s) => !s.user?.is_superadmin && s.user?.tenant?.agent_enabled === false);
  const [params, setParams] = useSearchParams();
  const activeRef = useRef<string | null>(null);
  const onActive = useCallback((id: string | null) => {
    activeRef.current = id;
  }, []);
  const { data: agents, isLoading } = useQuery({ queryKey: AGENT.agents(), queryFn: agentApi.agents, enabled: !tenantOff });
  const asked = params.get("view");
  const view: AssistantView = sup ? (asked === "debug" || asked === "simple" ? asked : (storedView() ?? "simple")) : "simple";

  const change = (v: AssistantView) => {
    storeView(v);
    const out = new URLSearchParams(params);
    out.set("view", v);
    if (v === "debug" && activeRef.current) out.set("session", activeRef.current);
    if (v === "simple") {
      out.delete("session");
      out.delete("agent");
    }
    setParams(out);
  };

  if (tenantOff) return <EmptyState icon={<Bot className="h-10 w-10" />} title={t("chat.agentOff")} />;
  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (!agents?.length) return <EmptyState icon={<Bot className="h-10 w-10" />} title={t("chat.noAgents")} />;
  const switcher = sup ? <ViewSwitch view={view} onChange={change} /> : null;
  if (view === "debug") return <DebugAssistant agents={agents} switcher={switcher} />;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-3" data-testid="assistant-page">
      {switcher ? <div className="flex shrink-0 justify-end">{switcher}</div> : null}
      <SimpleChat agent={agents[0]!} onActive={onActive} />
    </div>
  );
}
