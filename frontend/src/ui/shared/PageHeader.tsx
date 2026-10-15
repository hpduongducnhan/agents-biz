import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";

type SlotCtx = { slot: HTMLDivElement | null; setSlot: (el: HTMLDivElement | null) => void };
const PageHeaderContext = createContext<SlotCtx>({ slot: null, setSlot: () => {} });

/** Shell bọc quanh Header + nội dung trang — cấp context cho `PageHeaderSlot` / `PageHeaderPortal` (ui-system.md §3). */
export function PageHeaderProvider({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  return <PageHeaderContext.Provider value={{ slot, setSlot }}>{children}</PageHeaderContext.Provider>;
}

/** Header đặt ngay sau mô tả trang; rỗng thì ẩn. */
export function PageHeaderSlot({ className }: { className?: string }) {
  const { setSlot } = useContext(PageHeaderContext);
  return <div ref={setSlot} className={cn("flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground empty:hidden", className)} />;
}

/** Trang "gửi" thông tin phụ (thời điểm dữ liệu, nút làm mới…) lên cạnh mô tả trong Header. */
export function PageHeaderPortal({ children }: { children: ReactNode }) {
  const { slot } = useContext(PageHeaderContext);
  if (!slot) return null;
  return createPortal(children, slot);
}
