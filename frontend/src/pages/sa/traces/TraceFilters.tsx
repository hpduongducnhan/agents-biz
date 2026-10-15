import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { adminApi } from "@/features/admin/api";
import { ADMIN } from "@/features/admin/keys";
import { agentApi, studioApi } from "@/features/agent/api";
import { AGENT, STUDIO } from "@/features/agent/keys";
import { tenantsApi } from "@/features/tenant/api";
import { TENANTS } from "@/features/tenant/keys";
import { useT } from "@/lib/i18n";
import { Button, Input, Label, NativeSelect, Switch } from "@/ui";

import { STATUSES, useTraceFilters } from "./filters";

const LIST = { limit: 100 };
const TENANTS_Q = { q: null, limit: 100 };

/** Bộ lọc trace: tổ chức, user, phiên của user, agent, trạng thái, model, ngày, có lỗi. */
export function TraceFilters() {
  const t = useT();
  const { values, set, clear } = useTraceFilters();
  const tenants = useQuery({ queryKey: TENANTS.all(TENANTS_Q), queryFn: () => tenantsApi.list(TENANTS_Q) });
  const users = useQuery({ queryKey: ADMIN.users(LIST), queryFn: () => adminApi.listUsers(LIST) });
  const agents = useQuery({ queryKey: STUDIO.agents(), queryFn: studioApi.agents });
  const models = useQuery({ queryKey: STUDIO.models(), queryFn: studioApi.models });
  const sq = { user_id: values.user_id ?? "", limit: 100 };
  const sessions = useQuery({ queryKey: AGENT.sessions(sq), queryFn: () => agentApi.sessions(sq), enabled: !!values.user_id });
  const codes = [...new Set((models.data ?? []).map((m) => m.model_id))].sort();
  const any = Object.keys(values).length > 0;
  return (
    <div className="grid gap-2" data-testid="trace-filters">
      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        <NativeSelect aria-label={t("traces.filter.tenant")} className="min-w-0 sm:w-44" value={values.tenant_id ?? ""} onChange={(e) => set({ tenant_id: e.target.value || null })} data-testid="trace-tenant">
          <option value="">{t("traces.filter.allTenants")}</option>
          {(tenants.data?.items ?? []).map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label={t("trace.filter.user")} className="min-w-0 sm:w-48" value={values.user_id ?? ""} onChange={(e) => set({ user_id: e.target.value || null })} data-testid="trace-user">
          <option value="">{t("trace.filter.allUsers")}</option>
          {(users.data?.items ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.name || u.email}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          aria-label={t("trace.filter.session")}
          className="min-w-0 sm:w-56"
          value={values.session_id ?? ""}
          disabled={!values.user_id && !values.session_id}
          onChange={(e) => set({ session_id: e.target.value || null })}
          data-testid="trace-session"
        >
          <option value="">{t("trace.filter.allSessions")}</option>
          {values.session_id && !(sessions.data?.items ?? []).some((s) => s.id === values.session_id) ? <option value={values.session_id}>{values.session_id.slice(0, 8)}</option> : null}
          {(sessions.data?.items ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {(s.title || s.id.slice(0, 8)).slice(0, 60)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label={t("trace.filter.agent")} className="min-w-0 sm:w-44" value={values.agent_id ?? ""} onChange={(e) => set({ agent_id: e.target.value || null })} data-testid="trace-agent">
          <option value="">{t("trace.filter.allAgents")}</option>
          {(agents.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label={t("trace.status")} className="min-w-0 sm:w-40" value={values.status ?? ""} onChange={(e) => set({ status: e.target.value || null })} data-testid="trace-status">
          <option value="">{t("trace.status.all")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`trace.status.${s}`)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect aria-label={t("trace.filter.model")} className="min-w-0 sm:w-48" value={values.model ?? ""} onChange={(e) => set({ model: e.target.value || null })} data-testid="trace-model">
          <option value="">{t("trace.filter.allModels")}</option>
          {codes.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </NativeSelect>
        <div className="grid gap-1">
          <Label htmlFor="trace-since" className="text-xs text-muted-foreground">
            {t("trace.filter.since")}
          </Label>
          <Input id="trace-since" type="date" className="sm:w-40" value={values.since ?? ""} onChange={(e) => set({ since: e.target.value || null })} data-testid="trace-since" />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="trace-until" className="text-xs text-muted-foreground">
            {t("trace.filter.until")}
          </Label>
          <Input id="trace-until" type="date" className="sm:w-40" value={values.until ?? ""} onChange={(e) => set({ until: e.target.value || null })} data-testid="trace-until" />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Switch id="trace-has-error" checked={values.has_error === "1"} onCheckedChange={(v) => set({ has_error: v ? "1" : null })} data-testid="trace-has-error" />
          <Label htmlFor="trace-has-error">{t("trace.filter.hasError")}</Label>
        </div>
        {any && (
          <Button size="sm" variant="ghost" onClick={clear} data-testid="trace-clear">
            <X className="h-4 w-4" />
            {t("trace.filter.clear")}
          </Button>
        )}
      </div>
    </div>
  );
}
