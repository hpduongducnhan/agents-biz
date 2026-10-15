import { useQuery } from "@tanstack/react-query";

import { systemApi } from "./api";
import { SYSTEM } from "./keys";

/** Thông tin công khai (cờ đăng ký / Google) — trang đăng nhập dùng, lỗi thì im (form vẫn chạy). */
export function usePublicInfo() {
  return useQuery({ queryKey: SYSTEM.publicInfo(), queryFn: systemApi.publicInfo, staleTime: 5 * 60_000, meta: { silent: true } });
}
