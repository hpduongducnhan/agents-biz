import { useT } from "@/lib/i18n";

export function FormAlert({ text, cid }: { text: string; cid?: string | null }) {
  const t = useT();
  return (
    <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
      <p className="break-words">{text}</p>
      {cid ? (
        <p className="mt-1 font-mono text-xs opacity-90" data-testid="error-cid">
          {t("error.lookup", { cid })}
        </p>
      ) : null}
    </div>
  );
}
