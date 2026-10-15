import { mkKeys } from "@/lib/keys";

export const OBS = mkKeys("observability", {
  events: (q: object) => ["events", q],
  issues: (q: object) => ["issues", q],
  issue: (fingerprint: string) => ["issues", "detail", fingerprint],
});
