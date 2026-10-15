import { mkKeys } from "@/lib/keys";

export const RBAC = mkKeys("rbac", { permissions: () => ["permissions"], roles: () => ["roles"] });
