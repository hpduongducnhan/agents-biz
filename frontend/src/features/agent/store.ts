/**
 * Trạng thái một lượt đang stream — áp sự kiện `agent:*` theo `seq`:
 * sự kiện cũ / trùng bị bỏ (không nhân đôi chữ), hở `seq` thì báo `gap` để lấy phần thiếu qua `agent.run_events`.
 */
import type { ApprovalRow } from "./api";
import { type Dot, failTrail, firstLine, upsert } from "./trail";

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";
export type ApprovalState = {
  approvalId: string;
  callId: string;
  name: string;
  title: string;
  args: unknown;
  expiresAt: string;
  status: ApprovalStatus;
  reason?: string | null;
  by?: AgentTag;
};
export type AgentTag = { agent_id: string; slug: string; name: string };
export type StepState = { callId: string; name: string; title: string; status: "running" | "done" | "error"; args?: unknown; preview?: string; by?: AgentTag };
/** Một khối của lượt — mỗi chuyên gia một khối theo thứ tự chạy; agent đơn: một khối không `by`. */
export type Block = { by?: AgentTag; text: string };
export type RouteState = { steps: (AgentTag & { task: string })[]; clarify: string | null };
export type LiveRun = {
  runId: string;
  sessionId: string;
  lastSeq: number;
  text: string;
  steps: StepState[];
  approvals: ApprovalState[];
  status: "running" | "waiting" | "done" | "cancelled" | "failed";
  blocks: Block[];
  route?: RouteState;
  messageId?: string | null;
  error?: { code: number; message: string };
  /** Hàng chấm tiến trình theo thứ tự sự kiện. */
  trail: Dot[];
  /** Lượt có stream không (`agent:start.stream`); chưa biết = có. */
  stream?: boolean;
};
export type RunEventName =
  | "agent:start"
  | "agent:route"
  | "agent:token"
  | "agent:step"
  | "agent:llm"
  | "agent:approval"
  | "agent:approval_decided"
  | "agent:end"
  | "agent:error";
export type RunEvent = { event: RunEventName; data: { run_id: string; session_id: string; seq: number } & Record<string, unknown> };

export const RUN_EVENTS: RunEventName[] = ["agent:start", "agent:route", "agent:token", "agent:step", "agent:llm", "agent:approval", "agent:approval_decided", "agent:end", "agent:error"];

export const newRun = (runId: string, sessionId: string): LiveRun => ({
  runId,
  sessionId,
  lastSeq: 0,
  text: "",
  steps: [],
  approvals: [],
  blocks: [],
  trail: [],
  status: "running",
});

const tagOf = (v: unknown): AgentTag | undefined =>
  v && typeof v === "object" && "slug" in v
    ? { agent_id: String((v as AgentTag).agent_id ?? ""), slug: String((v as AgentTag).slug), name: String((v as AgentTag).name ?? "") }
    : undefined;

/** Thêm chữ vào khối của chuyên gia đang nói — đổi chuyên gia (hoặc chưa có khối) thì mở khối mới. */
function addText(blocks: Block[], by: AgentTag | undefined, delta: string): Block[] {
  const last = blocks[blocks.length - 1];
  if (last && last.by?.slug === by?.slug) return [...blocks.slice(0, -1), { ...last, text: last.text + delta }];
  return [...blocks, { by, text: delta }];
}

/** Mở khối cho chuyên gia khi bước tool / thẻ duyệt của nó tới trước chữ. */
function touch(blocks: Block[], by: AgentTag | undefined): Block[] {
  const last = blocks[blocks.length - 1];
  return last && last.by?.slug === by?.slug ? blocks : [...blocks, { by, text: "" }];
}
export const isOpen = (run: LiveRun | null | undefined) => run?.status === "running" || run?.status === "waiting";

/** Lượt chờ duyệt lâu hơn tuổi bộ đệm sự kiện (1 giờ) → dựng thẻ duyệt từ `agent.get_session`. */
export function withApprovals(run: LiveRun, rows: ApprovalRow[]): LiveRun {
  const approvals: ApprovalState[] = rows.map((a) => ({
    approvalId: a.id,
    callId: a.tool_call_id,
    name: a.operation,
    title: a.operation,
    args: a.args,
    expiresAt: a.expires_at,
    status: a.status as ApprovalStatus,
    reason: a.reason,
  }));
  let trail = run.trail;
  for (const a of approvals) trail = upsert(trail, approvalDot(a));
  return { ...run, approvals, trail, status: approvals.some((a) => a.status === "pending") ? "waiting" : run.status };
}

const approvalDot = (a: ApprovalState): Dot => ({
  key: `approval:${a.approvalId}`,
  kind: "approval",
  status: a.status === "pending" ? "waiting" : a.status === "approved" ? "ok" : "error",
  label: a.title,
  detail: a.status,
  by: a.by?.name,
});

const STEP_DOT = { running: "running", done: "ok", error: "error" } as const;

function apply(run: LiveRun, { event, data }: RunEvent): LiveRun {
  const next = { ...run, lastSeq: data.seq };
  switch (event) {
    case "agent:start":
      return { ...next, stream: data.stream !== false };
    case "agent:route": {
      const steps = ((data.steps as Record<string, unknown>[] | undefined) ?? []).map((x) => ({ ...tagOf(x)!, task: String(x.task ?? "") }));
      const dot: Dot = { key: "route", kind: "route", status: "ok", items: steps.map((x) => x.name) };
      return { ...next, route: { steps, clarify: (data.clarify as string | null | undefined) ?? null }, trail: upsert(run.trail, dot) };
    }
    case "agent:llm": {
      const tools = (data.tools as { name?: string; title?: string }[] | undefined) ?? [];
      const dot: Dot = {
        key: `llm:${data.seq}`,
        kind: "llm",
        status: data.status === "error" ? "error" : "ok",
        items: tools.map((x) => String(x.title ?? x.name ?? "")),
        ms: typeof data.ms === "number" ? data.ms : undefined,
        by: tagOf(data.by)?.name,
      };
      return { ...next, trail: upsert(run.trail, dot) };
    }
    case "agent:token": {
      const delta = String(data.delta ?? "");
      return { ...next, text: run.text + delta, blocks: addText(run.blocks, tagOf(data.by), delta) };
    }
    case "agent:step": {
      const callId = String(data.call_id);
      const found = run.steps.find((s) => s.callId === callId);
      const step: StepState = {
        callId,
        name: String(data.name),
        title: String(data.title ?? data.name),
        status: data.status as StepState["status"],
        ...(data.args !== undefined ? { args: data.args } : found?.args !== undefined ? { args: found.args } : {}),
        ...(data.preview !== undefined ? { preview: String(data.preview) } : {}),
        ...(tagOf(data.by) ? { by: tagOf(data.by) } : {}),
      };
      const steps = found ? run.steps.map((s) => (s.callId === callId ? step : s)) : [...run.steps, step];
      const dot: Dot = {
        key: `tool:${callId}`,
        kind: "tool",
        status: STEP_DOT[step.status] ?? "error",
        label: step.title,
        name: step.name,
        detail: step.status === "error" ? firstLine(step.preview) : undefined,
        by: (step.by ?? found?.by)?.name,
      };
      return { ...next, steps, trail: upsert(run.trail, dot), blocks: found ? run.blocks : touch(run.blocks, tagOf(data.by)) };
    }
    case "agent:approval": {
      const approval: ApprovalState = {
        approvalId: String(data.approval_id),
        callId: String(data.call_id),
        name: String(data.name),
        title: String(data.title ?? data.name),
        args: data.args,
        expiresAt: String(data.expires_at ?? ""),
        status: "pending",
        ...(tagOf(data.by) ? { by: tagOf(data.by) } : {}),
      };
      const approvals = [...run.approvals.filter((a) => a.approvalId !== approval.approvalId), approval];
      return { ...next, status: "waiting", approvals, trail: upsert(run.trail, approvalDot(approval)), blocks: touch(run.blocks, tagOf(data.by)) };
    }
    case "agent:approval_decided": {
      const approvals = run.approvals.map((a) =>
        a.approvalId === String(data.approval_id) ? { ...a, status: data.status as ApprovalStatus, reason: (data.reason as string | null) ?? null } : a,
      );
      const decided = approvals.find((a) => a.approvalId === String(data.approval_id));
      return { ...next, approvals, trail: decided ? upsert(run.trail, approvalDot(decided)) : run.trail, status: "running" };
    }
    case "agent:end":
      return { ...next, status: data.status === "cancelled" ? "cancelled" : "done", messageId: (data.message_id as string | null) ?? null };
    default: {
      const message = String(data.message ?? "");
      return { ...next, status: "failed", error: { code: Number(data.code), message }, trail: failTrail(run.trail, message) };
    }
  }
}

export function applyEvent(run: LiveRun, ev: RunEvent): { run: LiveRun; gap: boolean } {
  if (ev.data.seq <= run.lastSeq) return { run, gap: false };
  if (ev.data.seq > run.lastSeq + 1) return { run, gap: true };
  return { run: apply(run, ev), gap: false };
}

/** Áp một loạt sự kiện (vd từ `after_seq`) theo thứ tự `seq`; dừng ở chỗ còn hở. */
export function applyMany(run: LiveRun, events: RunEvent[]): LiveRun {
  let out = run;
  for (const ev of [...events].sort((a, b) => a.data.seq - b.data.seq)) {
    const step = applyEvent(out, ev);
    if (step.gap) break;
    out = step.run;
  }
  return out;
}
