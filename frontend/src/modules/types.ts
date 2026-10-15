/** Manifest của một module nghiệp vụ (D25): lõi (menu, router, cụm nút nổi, Tổng quan, i18n) đọc registry — thêm module
 *  không sửa lõi. */
import type { LucideIcon } from "lucide-react";
import type { ComponentType, LazyExoticComponent } from "react";

import type { Pairs } from "@/lib/i18n/pairs";

type Lazy<P = object> = LazyExoticComponent<ComponentType<P>>;

export interface ModuleNav {
  id: string;
  to: string;
  label: string; // khoá i18n
  icon: LucideIcon;
  perm?: string;
}

export interface ModuleRoute {
  path: string; // không có "/" đầu, vd "tasks"
  title: string; // khoá i18n tiêu đề Header
  subtitle?: string;
  perm?: string;
  component: Lazy;
}

/** Nút "Thêm nhanh" (cụm nút nổi ở điện thoại) mở hộp thoại của module. */
export interface ModuleQuickAdd {
  id: string;
  label: string;
  icon: LucideIcon;
  perm?: string;
  dialog: Lazy<{ open: boolean; onOpenChange: (open: boolean) => void }>;
}

/** Thẻ trên trang Tổng quan. */
export interface ModuleWidget {
  id: string;
  perm?: string;
  component: Lazy;
}

export interface ModuleManifest {
  id: string;
  nav?: ModuleNav[];
  routes?: ModuleRoute[];
  quickAdd?: ModuleQuickAdd[];
  widgets?: ModuleWidget[];
  dict?: Pairs;
}
