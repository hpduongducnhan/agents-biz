import { BrandMark } from "@/layout/Brand";
import { useT } from "@/lib/i18n";

/** Màn trống của phiên mới: lời mời + câu mở đầu của agent (bấm là gửi). */
export function Starters({ starters, onPick }: { starters: string[]; onPick: (text: string) => void }) {
  const t = useT();
  return (
    <div className="flex flex-col items-center gap-4 py-8 text-center" data-testid="chat-empty">
      <BrandMark className="h-16 w-16" />
      <p className="max-w-sm text-sm text-muted-foreground">{t("chat.empty")}</p>
      {starters.length ? (
        <div className="grid w-full max-w-md gap-2">
          <span className="text-xs font-semibold uppercase text-muted-foreground">{t("chat.startersTitle")}</span>
          {starters.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onPick(s)}
              className="min-h-11 rounded-2xl border border-border bg-card px-4 py-2 text-left text-sm hover:bg-accent"
              data-testid="chat-starter"
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
