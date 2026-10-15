/** Dựng trang trong test: QueryClient riêng (không retry), router bộ nhớ, Tooltip, user giả. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { useAuthStore } from "@/lib/auth/store";
import type { Me } from "@/lib/auth/types";
import { useLocaleStore } from "@/lib/i18n";
import { TooltipProvider } from "@/ui";

import { me } from "./fixtures";

export function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

export function testClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

export function renderPage(node: ReactNode, opts: { path?: string; route?: string; user?: Me | null; extra?: ReactNode } = {}) {
  useLocaleStore.getState().setLocale("vi");
  useAuthStore.setState({ user: opts.user === undefined ? me() : opts.user, isAuthenticated: opts.user !== null });
  const client = testClient();
  const view = render(
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={0}>
        <MemoryRouter initialEntries={[opts.route ?? "/"]}>
          <Routes>
            <Route path={opts.path ?? "/"} element={node} />
            <Route path="*" element={<Where />} />
            {opts.extra}
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return Object.assign(view, { client });
}

/** Giả kích thước màn: true = từ md (bảng), false = dưới md (thẻ). */
export function setDesktop(on: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: on,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
