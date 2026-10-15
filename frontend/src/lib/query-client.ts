/** TanStack Query một chỗ: mặc định + onError toàn cục toast kèm "Mã tra cứu". */
import { QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/errors";
import { translate } from "@/lib/i18n";

/** Có bản dịch theo mã lỗi thì dùng; không thì message BE (đã theo Accept-Language). */
export function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return translate("error.generic");
  if (error.status === 0) return translate("err.network");
  if (error.code != null) {
    const key = `err.${error.code}`;
    const text = translate(key);
    if (text !== key) return text;
  }
  return error.message || translate("error.generic");
}

export function lookupText(error: unknown): string | undefined {
  return error instanceof ApiError && error.correlationId ? translate("error.lookup", { cid: error.correlationId }) : undefined;
}

export function toastError(error: unknown): void {
  if (error instanceof ApiError && error.status === 401) return;
  toast.error(errorText(error), { description: lookupText(error) });
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (count, error) => !(error instanceof ApiError && error.status > 0 && error.status < 500) && count < 2,
    },
    mutations: { retry: false },
  },
});

queryClient.getQueryCache().config.onError = (error, query) => {
  if (!query.meta?.silent) toastError(error);
};

queryClient.getMutationCache().config.onError = (error, _v, _c, mutation) => {
  if (!mutation.meta?.silent && !mutation.options.onError) toastError(error);
};
