import type { EventQuery } from "@/features/observability/api";
import { useT } from "@/lib/i18n";
import { Input, NativeSelect } from "@/ui";

export type EventFilterState = { actor_id: string; operation: string; source: string; ok: "" | "ok" | "fail"; since: string; until: string };
export const EMPTY_FILTERS: EventFilterState = { actor_id: "", operation: "", source: "", ok: "", since: "", until: "" };
const SOURCES = ["web", "agent", "system", "ws", "scheduler"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const LIMIT = 20;

/** Bộ lọc → query: bỏ ô trống; người làm phải là uuid (gõ dở không gọi API lỗi); ngày theo giờ máy → ISO UTC. */
export function toEventQuery(f: EventFilterState, offset: number): EventQuery {
  const actor = f.actor_id.trim();
  const op = f.operation.trim();
  return {
    limit: LIMIT,
    offset,
    ...(UUID.test(actor) ? { actor_id: actor } : {}),
    ...(op ? { operation: op } : {}),
    ...(f.source ? { source: f.source } : {}),
    ...(f.ok ? { ok: f.ok === "ok" } : {}),
    ...(f.since ? { since: new Date(`${f.since}T00:00:00`).toISOString() } : {}),
    ...(f.until ? { until: new Date(`${f.until}T23:59:59`).toISOString() } : {}),
  };
}

/** Hàng lọc một dòng `h-9` từ md (ui-system §3); dưới md xếp lưới 2 cột. Tên control ở aria-label. */
export function EventFilters({ value, onChange }: { value: EventFilterState; onChange: (v: EventFilterState) => void }) {
  const t = useT();
  const set = (patch: Partial<EventFilterState>) => onChange({ ...value, ...patch });
  return (
    <div className="grid grid-cols-2 gap-2 md:flex md:flex-wrap md:justify-end" data-testid="events-filters">
      <Input className="col-span-2 md:h-9 md:w-56" aria-label={t("obs.f.operation")} placeholder={t("obs.f.operation")} data-testid="events-filter-operation" value={value.operation} onChange={(e) => set({ operation: e.target.value })} />
      <Input className="col-span-2 font-mono md:h-9 md:w-72" aria-label={t("obs.f.actor")} placeholder={t("obs.f.actor")} data-testid="events-filter-actor" value={value.actor_id} onChange={(e) => set({ actor_id: e.target.value })} />
      <NativeSelect className="md:h-9 md:w-40" aria-label={t("obs.f.source")} data-testid="events-filter-source" value={value.source} onChange={(e) => set({ source: e.target.value })}>
        <option value="">{t("obs.f.anySource")}</option>
        {SOURCES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </NativeSelect>
      <NativeSelect className="md:h-9 md:w-40" aria-label={t("obs.f.result")} data-testid="events-filter-ok" value={value.ok} onChange={(e) => set({ ok: e.target.value === "ok" ? "ok" : e.target.value === "fail" ? "fail" : "" })}>
        <option value="">{t("obs.f.anyResult")}</option>
        <option value="ok">{t("obs.ok")}</option>
        <option value="fail">{t("obs.fail")}</option>
      </NativeSelect>
      <Input type="date" className="md:h-9 md:w-40" aria-label={t("obs.f.since")} data-testid="events-filter-since" value={value.since} onChange={(e) => set({ since: e.target.value })} />
      <Input type="date" className="md:h-9 md:w-40" aria-label={t("obs.f.until")} data-testid="events-filter-until" value={value.until} onChange={(e) => set({ until: e.target.value })} />
    </div>
  );
}
