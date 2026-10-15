import { type ReactNode, useEffect } from "react";

import { useT } from "@/lib/i18n";
import { usePageMeta } from "@/stores/ui.store";

/** Đặt tiêu đề + mô tả trang cho Header (key i18n) — nội dung trang không lặp heading. */
export function Titled({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  const t = useT();
  const set = usePageMeta((s) => s.set);
  const tt = t(title);
  const st = subtitle ? t(subtitle) : undefined;
  useEffect(() => set(tt, st), [set, tt, st]);
  return children;
}
