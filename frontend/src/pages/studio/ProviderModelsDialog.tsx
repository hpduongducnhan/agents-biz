import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { credentialsApi, type Provider, type RemoteModel, studioApi } from "@/features/agent/api";
import { CREDENTIALS, STUDIO } from "@/features/agent/keys";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { errorText, toastError } from "@/lib/query-client";
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Field, Input, Label, NativeSelect, Switch, TruncText } from "@/ui";

const BATCH = 100; // `studio.add_models` nhận tối đa 100 model / lần

function ctxText(t: ReturnType<typeof useT>, n: number | null | undefined): string | null {
  if (!n) return null;
  return n >= 1000 ? t("studio.ctxK", { n: Math.round(n / 1000) }) : String(n);
}

function priceText(m: RemoteModel): string | null {
  if (m.input_price_per_1m == null && m.output_price_per_1m == null) return null;
  return `$${Number(m.input_price_per_1m ?? 0)} / $${Number(m.output_price_per_1m ?? 0)}`;
}

/** Chọn model từ danh sách provider cung cấp (`studio.provider_models`) rồi thêm nhiều model một lần (`studio.add_models`)
 *  — thay cho gõ tay mã model. Mở từ tab Provider (cố định provider) hoặc tab Model (chọn provider). */
export function ProviderModelsDialog({ providers, providerId: initial, onClose }: { providers: Provider[]; providerId?: string; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [providerId, setProviderId] = useState(initial ?? providers[0]?.id ?? "");
  const [credId, setCredId] = useState("");
  const [q, setQ] = useState("");
  const [chatOnly, setChatOnly] = useState(true);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const creds = useQuery({ queryKey: CREDENTIALS.list({ limit: 100 }), queryFn: () => credentialsApi.list({ limit: 100 }) });
  const remote = useQuery({
    queryKey: STUDIO.providerModels(providerId, credId),
    queryFn: () => studioApi.providerModels(providerId, credId || undefined),
    enabled: !!providerId,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const provider = providers.find((p) => p.id === providerId);
  const usable = (creds.data?.items ?? []).filter((c) => !c.provider_id || c.provider_id === providerId);
  const all = remote.data?.models ?? [];
  const needle = q.trim().toLowerCase();
  const shown = useMemo(
    () => all.filter((m) => (!chatOnly || m.chat) && (!needle || m.name.toLowerCase().includes(needle) || m.model_id.toLowerCase().includes(needle))),
    [all, chatOnly, needle],
  );
  const add = useMutation({
    mutationFn: async () => {
      const chosen = all.filter((m) => picked.has(m.model_id));
      let added = 0;
      let skipped = 0;
      for (let i = 0; i < chosen.length; i += BATCH) {
        const out = await studioApi.addModels({
          provider_id: providerId,
          models: chosen.slice(i, i + BATCH).map((m) => ({
            model_id: m.model_id,
            name: m.name.slice(0, 100),
            context_window: m.context_window ?? null,
            input_price_per_1m: m.input_price_per_1m ?? "0",
            output_price_per_1m: m.output_price_per_1m ?? "0",
            cache_read_price_per_1m: m.cache_read_price_per_1m ?? "0",
          })),
        });
        added += out.added;
        skipped += out.skipped;
      }
      return { added, skipped };
    },
    onSuccess: async ({ added, skipped }) => {
      toast.success(t("studio.addedN", { added, skipped }));
      await Promise.all([STUDIO.models(), STUDIO.providers(), STUDIO.agents()].map((queryKey) => qc.invalidateQueries({ queryKey })));
      onClose();
    },
    onError: toastError,
  });
  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const err = remote.error;
  const detail = err instanceof ApiError ? (err.data as { detail?: string } | null)?.detail : undefined;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl" data-testid="provider-models-dialog">
        <DialogHeader>
          <DialogTitle className="break-words">{t("studio.pickTitle", { name: provider?.name ?? "" })}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          {!initial && (
            <Field id="pm-provider" label={t("studio.provider")}>
              <NativeSelect
                id="pm-provider"
                value={providerId}
                onChange={(e) => {
                  setProviderId(e.target.value);
                  setCredId("");
                  setPicked(new Set());
                }}
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          )}
          <Field id="pm-key" label={t("studio.testWith")}>
            <NativeSelect id="pm-key" data-testid="provider-models-key" value={credId} onChange={(e) => setCredId(e.target.value)}>
              <option value="">{t("studio.keyAuto")}</option>
              {usable.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {c.masked_hint}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-0 flex-1 basis-56">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input aria-label={t("studio.searchModels")} placeholder={t("studio.searchModels")} className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} data-testid="provider-models-search" />
          </div>
          <div className="flex items-center gap-2">
            <Switch id="pm-chat" checked={chatOnly} onCheckedChange={setChatOnly} />
            <Label htmlFor="pm-chat">{t("studio.chatOnly")}</Label>
          </div>
        </div>
        {remote.isLoading ? (
          <p className="text-sm text-muted-foreground">{t("studio.loadingModels")}</p>
        ) : err ? (
          <p role="alert" className="break-words text-sm text-destructive" data-testid="provider-models-error">
            {errorText(err)}
            {detail ? ` — ${detail}` : ""}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span data-testid="provider-models-count">{t("studio.remoteCount", { n: shown.length, ms: remote.data?.latency_ms ?? 0 })}</span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setPicked(new Set([...picked, ...shown.filter((m) => !m.added).map((m) => m.model_id)]))}
                data-testid="provider-models-all"
              >
                {t("studio.selectShown")}
              </Button>
              {picked.size > 0 && (
                <Button type="button" size="sm" variant="ghost" onClick={() => setPicked(new Set())}>
                  {t("studio.clearSel")}
                </Button>
              )}
            </div>
            {shown.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("studio.noRemote")}</p>
            ) : (
              <ul className="grid max-h-[45dvh] gap-1.5 overflow-y-auto pr-1" data-testid="provider-models-list">
                {shown.map((m) => {
                  const ctx = ctxText(t, m.context_window);
                  const price = priceText(m);
                  return (
                    <li key={m.model_id}>
                      <label
                        className={cn(
                          "flex min-w-0 items-start gap-3 rounded-xl border border-border bg-card p-2.5",
                          m.added ? "opacity-60" : "cursor-pointer hover:bg-accent",
                        )}
                        data-testid={`provider-model-${m.model_id}`}
                      >
                        <Checkbox className="mt-0.5" checked={m.added || picked.has(m.model_id)} disabled={m.added} onCheckedChange={() => toggle(m.model_id)} aria-label={m.name} />
                        <span className="min-w-0 flex-1">
                          <TruncText text={m.name} className="text-sm font-semibold" />
                          <TruncText text={m.model_id} mono className="text-xs text-muted-foreground" />
                          {(ctx || price) && <span className="block text-xs text-muted-foreground">{[ctx, price].filter(Boolean).join(" · ")}</span>}
                        </span>
                        {m.added && <Badge variant="secondary">{t("studio.modelAdded")}</Badge>}
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="text-xs text-muted-foreground">{t("studio.priceNote")}</p>
          </>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("common.close")}
          </Button>
          <Button type="button" disabled={picked.size === 0 || add.isPending} onClick={() => add.mutate()} data-testid="provider-models-add">
            {t("studio.addN", { n: picked.size })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
