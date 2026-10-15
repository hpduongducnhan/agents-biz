import { mkKeys } from "@/lib/keys";

export const NOTIF = mkKeys("notifications", { list: (q: object) => ["list", q], unread: () => ["unread"] });
