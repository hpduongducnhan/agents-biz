import { mkKeys } from "@/lib/keys";

export const SYSTEM = mkKeys("system", { publicInfo: () => ["public_info"], settings: () => ["settings"], status: () => ["status"] });
