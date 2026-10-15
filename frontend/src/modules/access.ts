/** Mục của module mà user được thấy (theo quyền khai trong manifest). */
import { hasPermission } from "@/lib/auth/permissions";
import type { Me } from "@/lib/auth/types";

import { MODULES } from "./registry";
import type { ModuleNav, ModuleQuickAdd, ModuleWidget } from "./types";

const allowed = <T extends { perm?: string }>(user: Me | null, items: T[]) => items.filter((x) => hasPermission(user, x.perm));

export function moduleNav(user: Me | null): ModuleNav[] {
  return allowed(user, MODULES.flatMap((m) => m.nav ?? []));
}

export function moduleQuickAdds(user: Me | null): ModuleQuickAdd[] {
  return allowed(user, MODULES.flatMap((m) => m.quickAdd ?? []));
}

export function moduleWidgets(user: Me | null): ModuleWidget[] {
  return allowed(user, MODULES.flatMap((m) => m.widgets ?? []));
}
