import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Bot, ListChecks, Plus, Search } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { useHasPermission } from "@/lib/auth/permissions";
import { cn } from "@/lib/cn";
import { fmt } from "@/lib/date";
import { useT } from "@/lib/i18n";
import { useIsDesktop } from "@/lib/use-media";
import { Badge, Button, Cell, EmptyState, Input, Row, ServerPagination, Skeleton, Switch, Table, TruncText } from "@/ui";

import { type __Mod__Item, type __Mod__Query, __mod__Api } from "../api";
import { ItemForm } from "../components/ItemForm";
import { __MOD__ } from "../keys";
import { __MOD___PERMS } from "../perms";

const VIEWS = ["open", "done", "all"] as const;
const LIMIT = 20;
type View = (typeof VIEWS)[number];

/** `/__route__` — danh sách __title_vi_lower__: lọc trạng thái / do tôi tạo / tìm (trên URL); bảng ở desktop, thẻ ở điện thoại (R16). */
export default function ListPage() {
  const t = useT();
  const desktop = useIsDesktop();
  const canEdit = useHasPermission(__MOD___PERMS.EDIT);
  const [params, setParams] = useSearchParams();
  const view = (VIEWS as readonly string[]).includes(params.get("view") ?? "") ? (params.get("view") as View) : "open";
  const mine = params.get("mine") === "1";
  const q = params.get("q") ?? "";
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const [editing, setEditing] = useState<__Mod__Item | "new" | null>(null);
  const set = (patch: Record<string, string | null>, keepOffset = false) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v) next.set(k, v);
          else next.delete(k);
        }
        if (!keepOffset) next.delete("offset");
        return next;
      },
      { replace: true },
    );
  const query: __Mod__Query = { ...(view !== "all" ? { status: view } : {}), ...(mine ? { mine: true } : {}), ...(q.trim() ? { q: q.trim() } : {}), limit: LIMIT, offset };
  const { data, isLoading } = useQuery({ queryKey: __MOD__.list(query), queryFn: () => __mod__Api.list(query), placeholderData: keepPreviousData });
  const items = data?.items ?? [];
  const status = (x: __Mod__Item) => <Badge variant={x.status === "done" ? "secondary" : "outline"}>{t(`__mod__.status.${x.status}`)}</Badge>;

  return (
    <div className="space-y-4" data-testid="__mod__-page">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl bg-muted p-1" role="tablist" aria-label={t("__mod__.field.status")}>
          {VIEWS.map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              onClick={() => set({ view: v === "open" ? null : v })}
              className={cn("min-h-9 rounded-lg px-3 text-sm font-semibold", view === v ? "bg-card shadow-sm" : "text-muted-foreground")}
              data-testid={`__mod__-view-${v}`}
            >
              {t(`__mod__.view.${v}`)}
            </button>
          ))}
        </div>
        <label className="flex min-h-11 items-center gap-2 text-sm font-semibold">
          <Switch checked={mine} onCheckedChange={(v) => set({ mine: v ? "1" : null })} data-testid="__mod__-mine" />
          {t("__mod__.mine")}
        </label>
        {canEdit && (
          <Button className="ml-auto" onClick={() => setEditing("new")} data-testid="__mod__-new">
            <Plus className="h-4 w-4" />
            {t("__mod__.new")}
          </Button>
        )}
      </div>
      <div className="relative sm:max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input className="pl-9" aria-label={t("__mod__.search")} placeholder={t("__mod__.search")} value={q} onChange={(e) => set({ q: e.target.value || null })} data-testid="__mod__-search" />
      </div>
      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : items.length === 0 ? (
        <EmptyState icon={<ListChecks className="h-10 w-10" />} title={t(mine || q || view !== "open" ? "__mod__.emptyFiltered" : "__mod__.empty")} />
      ) : desktop ? (
        <Table head={[t("__mod__.field.title"), t("__mod__.field.status"), ""]}>
          {items.map((x) => (
            <Row key={x.id} testId={`__mod__-${x.id}`} onClick={() => setEditing(x)} className="cursor-pointer">
              <Cell className="max-w-[420px] font-semibold">
                <TruncText text={x.title} />
              </Cell>
              <Cell>{status(x)}</Cell>
              <Cell className="whitespace-nowrap text-right text-xs text-muted-foreground">
                {x.source === "agent" && <Bot className="mr-1 inline h-3.5 w-3.5" aria-label={t("__mod__.byAgent")} />}
                {fmt(x.updated_at, "relative")}
              </Cell>
            </Row>
          ))}
        </Table>
      ) : (
        <ul className="space-y-2">
          {items.map((x) => (
            <li key={x.id}>
              <button type="button" onClick={() => setEditing(x)} className="grid w-full min-w-0 gap-1 rounded-2xl border border-border bg-card p-4 text-left shadow-card" data-testid={`__mod__-${x.id}`}>
                <span className="flex min-w-0 items-start gap-2">
                  <span className="min-w-0 flex-1 break-words font-bold">{x.title}</span>
                  {status(x)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {x.created_by?.name ?? "—"} · {fmt(x.updated_at, "relative")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {data && data.total > LIMIT && <ServerPagination offset={offset} limit={LIMIT} total={data.total} onChange={(o) => set({ offset: o ? String(o) : null }, true)} />}
      {editing && <ItemForm key={editing === "new" ? "new" : editing.id} open item={editing === "new" ? null : editing} onOpenChange={(v) => !v && setEditing(null)} />}
    </div>
  );
}
