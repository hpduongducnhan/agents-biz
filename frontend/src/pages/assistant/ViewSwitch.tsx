import { Bug, MessageCircle } from "lucide-react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";

export type AssistantView = "simple" | "debug";

/** Công tắc giao diện Trợ lý của superadmin: Đơn giản (như user) ↔ Gỡ lỗi (phiên, bước tool, JSON). */
export function ViewSwitch({ view, onChange }: { view: AssistantView; onChange: (v: AssistantView) => void }) {
  const t = useT();
  const items = [
    { id: "simple" as const, icon: MessageCircle, label: t("chat.view.simple") },
    { id: "debug" as const, icon: Bug, label: t("chat.view.debug") },
  ];
  return (
    <div className="inline-flex shrink-0 rounded-full border border-border bg-muted/40 p-0.5" role="radiogroup" aria-label={t("chat.view.label")} data-testid="assistant-view">
      {items.map(({ id, icon: Icon, label }) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={view === id}
          onClick={() => onChange(id)}
          className={cn(
            "inline-flex min-h-8 items-center gap-1 rounded-full px-2.5 text-xs font-medium",
            view === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
          )}
          data-testid={`assistant-view-${id}`}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ))}
    </div>
  );
}
