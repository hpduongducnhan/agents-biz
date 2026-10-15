import "@/index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import { configureHttp, socketPath } from "@/lib/api";
import { useAuthStore } from "@/lib/auth/store";
import { registerAll } from "@/lib/i18n/register";
import { registerPwa } from "@/lib/pwa";
import { queryClient } from "@/lib/query-client";
import { socketManager } from "@/lib/realtime/socket";

registerAll();
registerPwa();
configureHttp({
  onAuthFailure: () => {
    // refresh hỏng / bị thu hồi → xoá phiên một lần, về đăng nhập kèm `next` (R15)
    useAuthStore.getState().logout();
    const { pathname, search } = window.location;
    if (!pathname.startsWith("/login")) window.location.href = `/login?next=${encodeURIComponent(pathname + search)}`;
  },
});
socketManager.configure({
  url: window.location.origin,
  path: socketPath(),
  onReconnect: () => void queryClient.invalidateQueries(), // mất kết nối một lúc → dữ liệu có thể đã cũ
});

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
