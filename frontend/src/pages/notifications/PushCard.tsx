import { useQuery } from "@tanstack/react-query";
import { BellOff, BellRing } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { pushApi } from "@/features/push/api";
import { useT } from "@/lib/i18n";
import { disablePush, enablePush, type PushState, pushState } from "@/lib/push";
import { toastError } from "@/lib/query-client";
import { useUiStore } from "@/stores/ui.store";
import { Button, Card } from "@/ui";

/** "Thông báo trên máy này": bật / tắt Web Push cho trình duyệt hiện tại; máy chủ chưa bật → ẩn. */
export function PushCard() {
  const t = useT();
  const openGuide = useUiStore((s) => s.setInstallGuide);
  const { data: cfg } = useQuery({ queryKey: ["push", "config"], queryFn: () => pushApi.config(), staleTime: Infinity });
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void pushState().then(setState);
  }, []);
  if (!cfg?.enabled || !cfg.public_key || state === null) return null;
  const run = async (fn: () => Promise<PushState | void>, ok: string) => {
    setBusy(true);
    try {
      const next = await fn();
      const now = next ?? (await pushState());
      setState(now);
      if (now === "on" || ok === "push.off.done") toast.success(t(ok));
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  };
  const on = state === "on";
  return (
    <Card className="flex items-start gap-3 p-4" data-testid="push-card" data-state={state}>
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-brand-muted text-brand">
        {on ? <BellRing className="h-5 w-5" aria-hidden /> : <BellOff className="h-5 w-5" aria-hidden />}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <div>
          <p className="text-sm font-bold">{t("push.title")}</p>
          <p className="text-xs text-muted-foreground">{t(`push.state.${state}`)}</p>
        </div>
        {state === "needs-install" && (
          <Button size="sm" variant="outline" data-testid="push-install" onClick={() => openGuide(true)}>
            {t("pwa.addToHome")}
          </Button>
        )}
        {state === "off" && (
          <Button size="sm" data-testid="push-enable" disabled={busy} onClick={() => void run(() => enablePush(cfg.public_key ?? ""), "push.on.done")}>
            {t("push.enable")}
          </Button>
        )}
        {on && (
          <Button size="sm" variant="outline" data-testid="push-disable" disabled={busy} onClick={() => void run(disablePush, "push.off.done")}>
            {t("push.disable")}
          </Button>
        )}
      </div>
    </Card>
  );
}
