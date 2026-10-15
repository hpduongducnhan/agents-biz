/** Gộp mọi file dict/*.ts (mỗi key một cặp [vi, en]) rồi đăng ký — parity vi / en đúng theo cấu trúc. */
import { common } from "./dict/common";
import { ui } from "./dict/ui";
import { pages } from "./dict/pages";
import { rt } from "./dict/rt";
import { shell } from "./dict/shell";
import { auth } from "./dict/auth";
import { profile } from "./dict/profile";
import { notif } from "./dict/notif";
import { admin } from "./dict/admin";
import { roles } from "./dict/roles";
import { sa } from "./dict/sa";
import { obs } from "./dict/obs";
import { agentUi } from "./dict/agentUi";
import { studioUi } from "./dict/studioUi";
import { observeUi } from "./dict/observeUi";
import { guardUi } from "./dict/guardUi";
import { tenantUi } from "./dict/tenantUi";
import { MODULES } from "@/modules/registry";

import { registerDictionary } from "./index";
import type { Pairs } from "./pairs";

export const DICTIONARIES: Pairs[] = [
  common,
  ui,
  pages,
  rt,
  shell,
  auth,
  profile,
  notif,
  admin,
  roles,
  sa,
  obs,
  agentUi,
  studioUi,
  observeUi,
  guardUi,
  tenantUi,
  ...MODULES.flatMap((m) => (m.dict ? [m.dict] : [])), // từ điển module (D25)
];

export function duplicateKeys(list: Pairs[] = DICTIONARIES): string[] {
  const seen = new Set<string>();
  const dup: string[] = [];
  for (const pairs of list) {
    for (const key of Object.keys(pairs)) {
      if (seen.has(key)) dup.push(key);
      seen.add(key);
    }
  }
  return dup;
}

export function registerAll(list: Pairs[] = DICTIONARIES): void {
  const vi: Record<string, string> = {};
  const en: Record<string, string> = {};
  for (const pairs of list) {
    for (const [key, [v, e]] of Object.entries(pairs)) {
      vi[key] = v;
      en[key] = e;
    }
  }
  registerDictionary("vi", vi);
  registerDictionary("en", en);
}
