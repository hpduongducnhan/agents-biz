/**
 * Hàng chấm tiến trình của một lượt: mỗi chấm = một lần phân loại (router), một lần gọi mô hình, một thao tác,
 * một lần duyệt hoặc lỗi của lượt. Lượt đang chạy dựng từ sự kiện `agent:*` (store), lượt cũ dựng từ tin đã lưu.
 */
import type { ChatMessage } from "./api";

export type DotStatus = "running" | "ok" | "error" | "waiting";
export type DotKind = "route" | "llm" | "tool" | "approval" | "error" | "thinking";
export type Dot = {
  key: string;
  kind: DotKind;
  status: DotStatus;
  /** Tên thao tác (tool / duyệt), thông điệp lỗi. */
  label?: string;
  /** Tên tool gốc — `handoff` có nhãn riêng. */
  name?: string;
  /** route: chuyên gia nhận việc · llm: thao tác mô hình quyết định gọi (rỗng = soạn trả lời). */
  items?: string[];
  /** Kết quả lỗi rút gọn (tool), trạng thái duyệt (approval). */
  detail?: string;
  ms?: number;
  by?: string;
};

const LINE = 160;

/** Dòng đầu của kết quả tool / thông điệp lỗi, cắt ngắn cho tooltip. */
export const firstLine = (text: string | undefined) => {
  const line = (text ?? "").split("\n").find((x) => x.trim()) ?? "";
  return line.length > LINE ? `${line.slice(0, LINE - 1)}…` : line;
};

/** Thay chấm cùng `key` (giữ vị trí) hoặc thêm cuối hàng. */
export function upsert(trail: Dot[], dot: Dot): Dot[] {
  const i = trail.findIndex((d) => d.key === dot.key);
  if (i < 0) return [...trail, dot];
  return trail.map((d, j) => (j === i ? { ...d, ...dot } : d));
}

/** Lượt hỏng: thao tác còn đang chạy coi như lỗi, thêm chấm lỗi cuối hàng. */
export function failTrail(trail: Dot[], message: string): Dot[] {
  const closed = trail.map((d) => (d.status === "running" ? { ...d, status: "error" as const } : d));
  return upsert(closed, { key: "error", kind: "error", status: "error", label: message });
}

type Call = { id: string; name: string };
type Content = { text?: string; tool_calls?: Call[]; tool_call_id?: string; status?: string };

/** Chấm của một lượt đã lưu: mỗi tin assistant một chấm "suy nghĩ", mỗi tool call một chấm (đỏ khi tin tool lỗi). */
export function dotsOf(replies: ChatMessage[], titles: Record<string, string>, names: Record<string, string> = {}): Dot[] {
  const results = new Map<string, Content>();
  for (const m of replies) {
    const c = (m.content ?? {}) as Content;
    if (m.role === "tool" && c.tool_call_id) results.set(c.tool_call_id, c);
  }
  const out: Dot[] = [];
  for (const m of replies) {
    if (m.role !== "assistant") continue;
    const c = (m.content ?? {}) as Content;
    const calls = c.tool_calls ?? [];
    const by = m.agent_id ? names[m.agent_id] : undefined;
    out.push({ key: `llm:${m.id}`, kind: "llm", status: "ok", items: calls.map((tc) => titles[tc.name] ?? tc.name), by });
    for (const tc of calls) {
      const res = results.get(tc.id);
      const failed = res?.status === "error";
      out.push({
        key: `tool:${tc.id}`,
        kind: "tool",
        status: failed ? "error" : "ok",
        label: titles[tc.name] ?? tc.name,
        name: tc.name,
        detail: failed ? firstLine(res?.text) : undefined,
        by,
      });
    }
  }
  return out;
}

/** Nhóm tin theo lượt hội thoại: mỗi tin user mở một lượt, tin assistant / tool sau đó là phần trả lời. */
export type Turn = { key: string; user?: ChatMessage; replies: ChatMessage[] };

export function turnsOf(messages: ChatMessage[]): Turn[] {
  const out: Turn[] = [];
  for (const m of messages) {
    const last = out[out.length - 1];
    if (m.role === "user") out.push({ key: m.id, user: m, replies: [] });
    else if (last) last.replies.push(m);
    else out.push({ key: m.id, replies: [m] });
  }
  return out;
}
