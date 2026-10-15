import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";

type ToolbarCtx = { slot: HTMLDivElement | null; setSlot: (el: HTMLDivElement | null) => void };
const TabToolbarContext = createContext<ToolbarCtx>({ slot: null, setSlot: () => {} });

/** Bọc quanh `<Tabs>` — cấp context cho `TabToolbarSlot`/`TabToolbarPortal` bên trong (xem ui-system.md §3b). */
export function TabToolbarProvider({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  return <TabToolbarContext.Provider value={{ slot, setSlot }}>{children}</TabToolbarContext.Provider>;
}

/** Đặt cùng hàng với `TabsList` — `shrink-0` để nút hành động luôn hiển thị đủ, không bị bóp; `TabsList` (bọc `overflow-x-auto` ở trang cha) tự cuộn ngang khi nhiều tab. `max-w-full`: hàng cha `flex-wrap` mà nhiều nút hơn bề ngang (màn hẹp) thì vùng này xuống hàng và nút tự xuống dòng, không tràn / đè lên tab. */
export function TabToolbarSlot({ className }: { className?: string }) {
  const { setSlot } = useContext(TabToolbarContext);
  return <div ref={setSlot} className={cn("flex max-w-full shrink-0 flex-wrap items-center justify-end gap-2", className)} />;
}

/** Tab con dùng để "gửi" nút hành động (Tạo mới, view toggle...) lên `TabToolbarSlot` của trang cha. */
export function TabToolbarPortal({ children }: { children: ReactNode }) {
  const { slot } = useContext(TabToolbarContext);
  if (!slot) return null;
  return createPortal(children, slot);
}
