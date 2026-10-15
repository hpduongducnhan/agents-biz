import { mkKeys } from "@/lib/keys";

export const ADMIN = mkKeys("admin", {
  users: (q: object) => ["users", q],
  user: (id: string) => ["users", "detail", id],
  userPolicies: (id: string) => ["users", "policies", id],
});
