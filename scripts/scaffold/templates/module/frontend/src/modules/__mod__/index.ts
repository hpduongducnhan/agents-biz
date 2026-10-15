/** Manifest module __title_vi__ (D25 — sinh bằng `make new-module`). */
import { ListChecks } from "lucide-react";
import { lazy } from "react";

import type { ModuleManifest } from "../types";
import { __mod__Dict } from "./dict";
import { __MOD___PERMS } from "./perms";

export const __mod__Module: ModuleManifest = {
  id: "__mod__",
  nav: [{ id: "__mod__", to: "/__route__", label: "nav.__mod__", icon: ListChecks, perm: __MOD___PERMS.VIEW }],
  routes: [{ path: "__route__", title: "nav.__mod__", subtitle: "sub.__mod__", perm: __MOD___PERMS.VIEW, component: lazy(() => import("./pages/ListPage")) }],
  dict: __mod__Dict,
};
