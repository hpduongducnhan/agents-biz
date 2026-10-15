import { mkKeys } from "@/lib/keys";

/** Khớp `invalidates` của backend: `__mod__.list` · `__mod__.detail`. */
export const __MOD__ = mkKeys("__mod__", {
  list: (q: object = {}) => ["list", q],
  detail: (id: string) => ["detail", id],
});
