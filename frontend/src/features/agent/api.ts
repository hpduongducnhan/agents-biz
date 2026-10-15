import { call, type OpInput, type OpOutput } from "@/lib/api";

export type AgentCard = OpOutput<"agent.list_agents">[number];
export type ChatSession = OpOutput<"agent.list_sessions">["items"][number];
export type SessionDetail = OpOutput<"agent.get_session">;
export type CurrentSession = OpOutput<"agent.current_session">;
export type ChatMessage = SessionDetail["messages"][number];
export type ApprovalRow = SessionDetail["approvals"][number];
export type RunEvents = OpOutput<"agent.run_events">;
export type Provider = OpOutput<"studio.list_providers">[number];
export type Model = OpOutput<"studio.list_models">[number];
export type RemoteModel = OpOutput<"studio.provider_models">["models"][number];
export type StudioAgent = OpOutput<"studio.get_agent">;
export type Toolset = OpOutput<"studio.tool_catalog">[number];
export type Hook = OpOutput<"studio.list_hooks">[number];
export type Route = OpOutput<"studio.list_routes">[number];
export type Credential = OpOutput<"credentials.list">["items"][number];
export type TracePage = OpOutput<"traces.list">;
export type TraceTree = OpOutput<"traces.get">;
export type Span = TraceTree["spans"][number];
export type UsageSummary = OpOutput<"usage.summary">;
export type UsageRow = UsageSummary["rows"][number];
export type UsageQuery = OpInput<"usage.summary">;
export type LlmError = OpOutput<"usage.errors">["items"][number];
export type TraceQuery = OpInput<"traces.list">;

export const agentApi = {
  agents: () => call("agent.list_agents"),
  send: (input: OpInput<"agent.send">) => call("agent.send", input),
  current: (agent_id?: string) => call("agent.current_session", agent_id ? { agent_id } : {}),
  sessions: (q: OpInput<"agent.list_sessions"> = {}) => call("agent.list_sessions", q),
  session: (session_id: string) => call("agent.get_session", { session_id }),
  rename: (session_id: string, title: string) => call("agent.rename_session", { session_id, title }),
  remove: (session_id: string) => call("agent.delete_session", { session_id }),
  cancel: (run_id: string) => call("agent.cancel", { run_id }),
  decide: (approval_id: string, approve: boolean, reason: string | null) =>
    call("agent.decide_approval", { approval_id, approve, reason }),
  decideMany: (run_id: string, approval_ids: string[], approve: boolean, reason: string | null) =>
    call("agent.decide_approvals", { run_id, approval_ids, approve, reason }),
  runEvents: (run_id: string, after_seq: number) => call("agent.run_events", { run_id, after_seq }),
};

export const studioApi = {
  providers: () => call("studio.list_providers"),
  saveProvider: (input: OpInput<"studio.save_provider">) => call("studio.save_provider", input),
  deleteProvider: (id: string) => call("studio.delete_provider", { id }),
  testProvider: (provider_id: string, credential_id: string) => call("studio.test_provider", { provider_id, credential_id }),
  providerModels: (provider_id: string, credential_id?: string) =>
    call("studio.provider_models", credential_id ? { provider_id, credential_id } : { provider_id }),
  addModels: (input: OpInput<"studio.add_models">) => call("studio.add_models", input),
  models: () => call("studio.list_models"),
  saveModel: (input: OpInput<"studio.save_model">) => call("studio.save_model", input),
  deleteModel: (id: string) => call("studio.delete_model", { id }),
  agents: () => call("studio.list_agents"),
  agent: (agent_id: string) => call("studio.get_agent", { agent_id }),
  saveAgent: (input: OpInput<"studio.save_agent">) => call("studio.save_agent", input),
  setKeys: (input: OpInput<"studio.set_agent_keys">) => call("studio.set_agent_keys", input),
  setLimits: (input: OpInput<"studio.set_agent_limits">) => call("studio.set_agent_limits", input),
  setUserLimit: (input: OpInput<"studio.set_user_limit">) => call("studio.set_user_limit", input),
  setToolsets: (agent_id: string, toolsets: string[]) => call("studio.set_toolsets", { agent_id, toolsets }),
  setOverride: (input: OpInput<"studio.set_tool_override">) => call("studio.set_tool_override", input),
  configureAll: (input: OpInput<"studio.configure_all">) => call("studio.configure_all", input),
  catalog: () => call("studio.tool_catalog"),
  hooks: (agent_id: string) => call("studio.list_hooks", { agent_id }),
  saveHook: (input: OpInput<"studio.save_hook">) => call("studio.save_hook", input),
  deleteHook: (hook_id: string) => call("studio.delete_hook", { hook_id }),
  testHook: (input: OpInput<"studio.test_hook">) => call("studio.test_hook", input),
  routes: (orchestrator_id: string) => call("studio.list_routes", { orchestrator_id }),
  saveRoute: (input: OpInput<"studio.save_route">) => call("studio.save_route", input),
  deleteRoute: (orchestrator_id: string, agent_id: string) => call("studio.delete_route", { orchestrator_id, agent_id }),
  persona: () => call("studio.get_persona"),
  savePersona: (input: OpInput<"studio.save_persona">) => call("studio.save_persona", input),
};

export const credentialsApi = {
  list: (q: OpInput<"credentials.list"> = {}) => call("credentials.list", q),
  create: (input: OpInput<"credentials.create">) => call("credentials.create", input),
  update: (input: OpInput<"credentials.update">) => call("credentials.update", input),
  remove: (credential_id: string) => call("credentials.delete", { credential_id }),
};

export const traceApi = {
  list: (q: OpInput<"traces.list"> = {}) => call("traces.list", q),
  get: (run_id: string) => call("traces.get", { run_id }),
  raw: (run_id: string, raw_id: string) => call("traces.raw", { run_id, raw_id }),
  usage: (q: OpInput<"usage.summary"> = {}) => call("usage.summary", q),
  usageErrors: (q: OpInput<"usage.errors"> = {}) => call("usage.errors", q),
};
