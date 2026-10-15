import { call, type OpInput, type OpOutput } from "@/lib/api";

export type ChatLimits = OpOutput<"agent.chat_limits">;
export type ChatBlock = OpOutput<"studio.list_chat_blocks">["items"][number];

/** Chống spam trợ lý: hạn mức + chặn của chính mình; superadmin xem / chặn / mở chặn. */
export const guardApi = {
  chatLimits: () => call("agent.chat_limits"),
  listBlocks: (q: OpInput<"studio.list_chat_blocks">) => call("studio.list_chat_blocks", q),
  block: (input: OpInput<"studio.block_chat">) => call("studio.block_chat", input),
  unblock: (block_id: string) => call("studio.unblock_chat", { block_id }),
};
