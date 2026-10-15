import { mkKeys } from "@/lib/keys";

/** Khớp `invalidates` backend: `agent.sessions`, `agent.session`, `agent.agents`, `agent.chat_limits`. */
export const AGENT = mkKeys("agent", {
  agents: () => ["agents"],
  chatLimits: () => ["chat_limits"],
  sessions: (q: object = {}) => ["sessions", q],
  session: (id: string) => ["session", id],
});

/** `studio.providers` · `studio.models` · `studio.agents` · `studio.agent` · `studio.hooks` · `studio.routes` · `studio.persona`. */
export const STUDIO = mkKeys("studio", {
  providers: () => ["providers"],
  models: () => ["models"],
  providerModels: (providerId: string, credId: string) => ["provider_models", providerId, credId],
  agents: () => ["agents"],
  agent: (id: string) => ["agent", id],
  catalog: () => ["catalog"],
  hooks: (agentId: string) => ["hooks", agentId],
  routes: (agentId: string) => ["routes", agentId],
  persona: () => ["persona"],
  chatBlocks: (q: object = {}) => ["chat_blocks", q],
});

export const CREDENTIALS = mkKeys("credentials", { list: (q: object = {}) => ["list", q] });

export const TRACES = mkKeys("traces", {
  list: (q: object = {}) => ["list", q],
  get: (runId: string) => ["get", runId],
  raw: (runId: string, rawId: string) => ["raw", runId, rawId],
});

export const USAGE = mkKeys("usage", { summary: (q: object = {}) => ["summary", q], errors: (q: object = {}) => ["errors", q] });
