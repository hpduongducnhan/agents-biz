import { Sparkles } from "lucide-react";
import { Suspense, useState } from "react";
import { NavLink, useLocation } from "react-router";

import { useCanUseAssistant, useCurrentUser } from "@/lib/auth/permissions";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { moduleQuickAdds } from "@/modules/access";
import type { ModuleQuickAdd } from "@/modules/types";

/** Điện thoại: một cụm nút nổi giữa đáy — Trợ lý nổi bật + nút "Thêm nhanh" của module (registry — D25). Không phủ cả
 *  chiều ngang nên không chồng thành "hai thanh" với thanh nút của trình duyệt. Ẩn ở trang Trợ lý (ô nhập chat ở đáy);
 *  không được dùng trợ lý thì chỉ còn nút của module. */
export function MobileDock() {
  const t = useT();
  const { pathname } = useLocation();
  const user = useCurrentUser();
  const assistant = useCanUseAssistant();
  const [open, setOpen] = useState<ModuleQuickAdd | null>(null);
  const adds = moduleQuickAdds(user);
  if (pathname.startsWith("/assistant") || (!assistant && adds.length === 0)) return null;
  const Dialog = open?.dialog;
  return (
    <>
      <div className="pointer-events-none fixed inset-x-0 bottom-[calc(0.75rem+env(safe-area-inset-bottom))] z-40 flex justify-center md:hidden" data-testid="mobile-dock">
        <div className="pointer-events-auto flex items-center gap-1.5 rounded-full border border-border bg-card/95 p-1.5 shadow-card backdrop-blur-md">
          {adds.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => setOpen(a)}
              aria-label={t(a.label)}
              className="flex h-12 items-center gap-2 rounded-full px-4 text-sm font-bold text-foreground hover:bg-accent"
              data-testid={`dock-add-${a.id}`}
            >
              <a.icon className="h-5 w-5" aria-hidden />
              {t(a.label)}
            </button>
          ))}
          {assistant && (
            <NavLink
              to="/assistant"
              data-testid="dock-assistant"
              className={({ isActive }) =>
                cn("flex h-12 items-center gap-2 rounded-full bg-primary px-5 text-sm font-extrabold text-primary-foreground shadow-card ring-2 ring-brand/30", isActive && "ring-brand")
              }
            >
              <Sparkles className="h-5 w-5" aria-hidden />
              {t("nav.assistant")}
            </NavLink>
          )}
        </div>
      </div>
      {Dialog && (
        <Suspense fallback={null}>
          <Dialog open onOpenChange={(v) => !v && setOpen(null)} />
        </Suspense>
      )}
    </>
  );
}
