/** Chỗ duy nhất ghép base URL của API / realtime (R15) — nơi khác chỉ truyền đường dẫn tương đối. */
import { API_BASE, WS_PATH } from "@/env";

const trimEnd = (s: string) => s.replace(/\/+$/, "");
const join = (base: string, path: string) => {
  const rest = path.replace(/^\/+/, "");
  return rest ? `${trimEnd(base)}/${rest}` : trimEnd(base);
};

export function apiUrl(path = ""): string {
  return join(API_BASE, path);
}

export function wsUrl(path = ""): string {
  return join(WS_PATH, path);
}

export function socketPath(): string {
  return `${wsUrl("socket.io")}/`;
}
