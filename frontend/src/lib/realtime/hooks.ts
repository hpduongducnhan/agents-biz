import { useCallback, useEffect, useRef } from "react";

import { type RealtimeHandler, type SendAck, socketManager, useSocketStatusStore } from "./socket";

/** Nghe event realtime; tự huỷ khi unmount. Handler mới nhất luôn được gọi (không cần useCallback). */
export function useRealtime(event: string, handler: RealtimeHandler): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => socketManager.on(event, (data, meta) => ref.current(data, meta)), [event]);
}

/** Gửi event `<miền>.<việc>` lên service realtime; ack = đã nhận yêu cầu (kết quả về qua event ra). */
export function useSendRealtime(): (event: string, data?: unknown) => Promise<SendAck> {
  return useCallback((event, data) => socketManager.send(event, data), []);
}

export function useSocketStatus() {
  return useSocketStatusStore((s) => s.status);
}
