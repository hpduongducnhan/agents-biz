import { mkKeys } from "@/lib/keys";

export const AUTH = mkKeys("auth", { me: () => ["me"] });
