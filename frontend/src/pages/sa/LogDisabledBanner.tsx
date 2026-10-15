import { DatabaseZap } from "lucide-react";

import { useT } from "@/lib/i18n";

/** API đọc log trả `enabled: false` khi MONGO_ENABLED=false — trạng thái bình thường, không phải lỗi. */
export function LogDisabledBanner() {
  const t = useT();
  return (
    <div role="status" data-testid="log-disabled-banner" className="flex items-start gap-3 rounded-2xl border border-warning/40 bg-warning/10 p-4 text-sm">
      <DatabaseZap className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden />
      <div className="min-w-0">
        <p className="font-bold">{t("obs.disabled.title")}</p>
        <p className="text-muted-foreground">{t("obs.disabled.desc")}</p>
      </div>
    </div>
  );
}
