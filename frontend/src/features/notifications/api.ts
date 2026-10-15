import type { QueryClient } from "@tanstack/react-query";

import { call, type OpInput, type OpOutput } from "@/lib/api";
import { socketManager } from "@/lib/realtime/socket";

import { NOTIF } from "./keys";

export type Notification = OpOutput<"notifications.list">["items"][number];
export type NotifQuery = OpInput<"notifications.list">;

export const notificationsApi = {
  list: (q: NotifQuery) => call("notifications.list", q),
  unreadCount: () => call("notifications.unread_count"),
  markRead: (ids: string[]) => call("notifications.mark_read", { ids }),
  markAllRead: () => call("notifications.mark_all_read"),
  sendTest: (input: OpInput<"notifications.send_test">) => call("notifications.send_test", input),
};

/** Đánh dấu đã đọc: qua socket khi đang nối (thao tác nhẹ — R18), kết quả về qua `data:changed`;
 *  socket không nối → REST rồi tự làm mới (không có `data:changed` nào tới được). */
export async function markReadFast(qc: QueryClient, ids: string[]): Promise<void> {
  const ack = await socketManager.send("notifications.mark_read", { ids });
  if (ack.accepted) return;
  await notificationsApi.markRead(ids);
  await qc.invalidateQueries({ queryKey: NOTIF.all });
}
