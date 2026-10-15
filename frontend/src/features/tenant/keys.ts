import { mkKeys } from "@/lib/keys";

/** Khớp `app/tenants/qkeys.py`: `tenant.current` · `tenant.invites` · `tenants.all`. */
export const TENANT = mkKeys("tenant", { current: () => ["current"], invites: () => ["invites"] });
export const TENANTS = mkKeys("tenants", { all: (q: object = {}) => ["all", q] });
export const MAIL = mkKeys("mail", { outbox: () => ["outbox"] });
