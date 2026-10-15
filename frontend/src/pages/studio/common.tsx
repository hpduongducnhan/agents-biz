/** Mảnh dùng chung của Agent Studio: ô JSON, thẻ một dòng cấu hình, nút của tab trên hàng tab, mutation có làm mới + toast. */
import { type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";

import { useT } from "@/lib/i18n";
import { toastError } from "@/lib/query-client";
import { Badge, Field, Textarea } from "@/ui";

export function parseJson(text: string): { ok: true; value: Record<string, unknown> } | { ok: false } {
  if (!text.trim()) return { ok: true, value: {} };
  try {
    const value: unknown = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value) ? { ok: true, value: value as Record<string, unknown> } : { ok: false };
  } catch {
    return { ok: false };
  }
}

export const jsonText = (v: unknown) => (v && typeof v === "object" && Object.keys(v).length ? JSON.stringify(v, null, 2) : "");

export function JsonField({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  const t = useT();
  const bad = !parseJson(value).ok;
  return (
    <Field id={id} label={label} error={bad ? t("studio.jsonInvalid") : undefined}>
      <Textarea id={id} rows={3} className="font-mono text-xs" value={value} onChange={(e) => onChange(e.target.value)} spellCheck={false} />
    </Field>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const t = useT();
  return <Badge variant={status === "active" ? "secondary" : "outline"}>{t(`studio.status.${status}`)}</Badge>;
}

/** Một dòng cấu hình dạng thẻ (R16: điện thoại dùng thẻ, không bảng cuộn ngang). */
export function ItemCard({ title, meta, badges, actions, testId }: { title: ReactNode; meta?: ReactNode; badges?: ReactNode; actions?: ReactNode; testId?: string }) {
  return (
    <li className="flex min-w-0 flex-wrap items-center gap-3 rounded-2xl border border-border bg-card p-3" data-testid={testId}>
      <div className="grid min-w-0 flex-1 gap-0.5">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="truncate font-semibold">{title}</span>
          {badges}
        </div>
        {meta ? <div className="truncate text-xs text-muted-foreground">{meta}</div> : null}
      </div>
      {actions ? <div className="flex max-w-full flex-wrap items-center gap-1">{actions}</div> : null}
    </li>
  );
}

/** Chỗ đặt nút của tab ở hàng tab: `undefined` = không nằm trong StudioPage, `null` = chỗ chưa gắn vào DOM. */
const ActionsSlot = createContext<HTMLElement | null | undefined>(undefined);
export const StudioActionsSlot = ActionsSlot.Provider;

/** Nút cấp tab (Agent mới, Thêm…): lên ngang hàng tab của StudioPage; render riêng một tab thì hiện tại chỗ. */
export function TabActions({ children }: { children: ReactNode }) {
  const slot = useContext(ActionsSlot);
  if (slot === undefined) return <div className="flex flex-wrap gap-2">{children}</div>;
  return slot ? createPortal(children, slot) : null;
}

/** Mutation của Studio: thành công → toast "Đã lưu" + làm mới các key; lỗi → toast (mã lỗi dịch được). */
export function useStudioMutation<I, O>(fn: (input: I) => Promise<O>, keys: QueryKey[], onDone?: (out: O) => void) {
  const t = useT();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async (out) => {
      toast.success(t("studio.saved"));
      await Promise.all(keys.map((queryKey) => qc.invalidateQueries({ queryKey })));
      onDone?.(out);
    },
    onError: toastError,
  });
}
