import { ChevronLeft, ChevronRight } from "lucide-react";

import { useT } from "@/lib/i18n";
import { Button } from "../button";

type Props = { offset: number; limit: number; total: number; onChange: (offset: number) => void };

/** Phân trang server (offset / limit) cho danh sách `{items, total}` của API lõi. */
export function ServerPagination({ offset, limit, total, onChange }: Props) {
  const t = useT();
  if (total <= limit) return null;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
      <span className="tabular-nums">{t("common.range", { from, to, total })}</span>
      <Button size="icon" variant="outline" aria-label={t("common.prev")} disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <Button size="icon" variant="outline" aria-label={t("common.next")} disabled={to >= total} onClick={() => onChange(offset + limit)}>
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}
