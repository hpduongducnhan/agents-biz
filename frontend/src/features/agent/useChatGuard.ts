import { useQuery } from "@tanstack/react-query";

import { type ChatLimits, guardApi } from "./guardApi";
import { AGENT } from "./keys";

export type ChatGuard = { blocked: ChatLimits["blocked"]; leftToday: number | null };

/** Hạn mức + chặn tạm của chính mình — làm mới qua `data:changed agent.chat_limits` (gửi tin, bị chặn / mở). */
export function useChatGuard(): ChatGuard {
  const { data } = useQuery({ queryKey: AGENT.chatLimits(), queryFn: () => guardApi.chatLimits(), staleTime: 30_000 });
  const day = data?.windows.find((w) => w.window === "day");
  const left = day?.limit != null ? Math.max(0, day.limit - day.used) : null;
  // chỉ nhắc khi còn ít: ≤ 20 % trần ngày (tối thiểu 5 tin)
  const near = left != null && day?.limit != null && left <= Math.max(5, Math.floor(day.limit * 0.2));
  return { blocked: data?.blocked ?? null, leftToday: near ? left : null };
}
