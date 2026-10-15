import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { adminApi } from "@/features/admin/api";
import { ADMIN } from "@/features/admin/keys";
import { credentialsApi, studioApi } from "@/features/agent/api";
import { CREDENTIALS, STUDIO } from "@/features/agent/keys";
import { tenantsApi } from "@/features/tenant/api";
import { TENANTS } from "@/features/tenant/keys";
import { useT } from "@/lib/i18n";
import { Button, NativeSelect } from "@/ui";

import { type FilterKey, RANGES, useUsageFilters } from "./filters";

const USERS_Q = { limit: 100 };
const TENANTS_Q = { q: null, limit: 100 };

/** Danh sách cho các ô chọn + tên hiện trên nhãn bộ lọc (dùng chung với bảng phân tích). */
export function useUsageOptions() {
  const tenants = useQuery({ queryKey: TENANTS.all(TENANTS_Q), queryFn: () => tenantsApi.list(TENANTS_Q) });
  const users = useQuery({ queryKey: ADMIN.users(USERS_Q), queryFn: () => adminApi.listUsers(USERS_Q) });
  const agents = useQuery({ queryKey: STUDIO.agents(), queryFn: studioApi.agents });
  const models = useQuery({ queryKey: STUDIO.models(), queryFn: studioApi.models });
  const providers = useQuery({ queryKey: STUDIO.providers(), queryFn: studioApi.providers });
  const keys = useQuery({ queryKey: CREDENTIALS.list({ limit: 100 }), queryFn: () => credentialsApi.list({ limit: 100 }) });
  return {
    tenant_id: (tenants.data?.items ?? []).map((x) => ({ id: x.id, name: x.name })),
    user_id: (users.data?.items ?? []).map((u) => ({ id: u.id, name: u.name || u.email })),
    agent_id: (agents.data ?? []).map((a) => ({ id: a.id, name: a.name })),
    model_id: (models.data ?? []).map((m) => ({ id: m.id, name: `${m.name} · ${m.model_id}` })),
    provider_id: (providers.data ?? []).map((p) => ({ id: p.id, name: p.name })),
    credential_id: (keys.data?.items ?? []).map((c) => ({ id: c.id, name: `${c.name} · ${c.masked_hint}` })),
  } as Record<Exclude<FilterKey, "purpose" | "session_id">, { id: string; name: string }[]>;
}

const SELECTS = ["tenant_id", "user_id", "agent_id", "model_id", "provider_id", "credential_id"] as const;

export function UsageFilters() {
  const t = useT();
  const { range, filters, set, clear } = useUsageFilters();
  const options = useUsageOptions();
  const label: Record<FilterKey, string> = {
    tenant_id: t("usage.filter.tenant"),
    user_id: t("usage.filter.user"),
    agent_id: t("usage.filter.agent"),
    model_id: t("usage.filter.model"),
    provider_id: t("usage.filter.provider"),
    credential_id: t("usage.filter.key"),
    purpose: t("usage.filter.purpose"),
    session_id: t("usage.filter.session"),
  };
  const any = Object.keys(filters).length > 0;
  return (
    <div className="grid gap-2" data-testid="usage-filters">
      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        <NativeSelect aria-label={t("usage.range")} className="sm:w-36" value={range} onChange={(e) => set({ range: e.target.value })} data-testid="usage-range">
          {RANGES.map((d) => (
            <option key={d} value={d}>
              {t(`usage.range.${d}`)}
            </option>
          ))}
        </NativeSelect>
        {SELECTS.map((k) => (
          <NativeSelect key={k} aria-label={label[k]} className="min-w-0 sm:w-44" value={filters[k] ?? ""} onChange={(e) => set({ [k]: e.target.value || null })} data-testid={`usage-filter-${k}`}>
            <option value="">
              {label[k]}: {t("usage.filter.all")}
            </option>
            {options[k].map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </NativeSelect>
        ))}
        <NativeSelect aria-label={label.purpose} className="min-w-0 sm:w-44" value={filters.purpose ?? ""} onChange={(e) => set({ purpose: e.target.value || null })} data-testid="usage-filter-purpose">
          <option value="">
            {label.purpose}: {t("usage.filter.all")}
          </option>
          <option value="router">{t("usage.purpose.router")}</option>
          <option value="agent">{t("usage.purpose.agent")}</option>
        </NativeSelect>
      </div>
      {any && (
        <div className="flex flex-wrap items-center gap-2">
          {filters.session_id && (
            <Button size="sm" variant="secondary" onClick={() => set({ session_id: null })} data-testid="usage-chip-session">
              {label.session_id}: {filters.session_id.slice(0, 8)}
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={clear} data-testid="usage-clear">
            <X className="h-4 w-4" />
            {t("usage.filter.clear")}
          </Button>
        </div>
      )}
    </div>
  );
}
