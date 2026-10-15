/** Route của app (data router, dựng một lần). Mỗi trang: tiêu đề Header → error boundary → Suspense (trang lazy). */
import { Component, lazy, type ReactNode, Suspense } from "react";
import { createBrowserRouter, type RouteObject } from "react-router";

import { ProtectedRoute, RequirePermission, RequireSuperadmin } from "@/guards/guards";
import { AppShell } from "@/layout/AppShell";
import { Titled } from "@/layout/Titled";
import { PERMS } from "@/lib/auth/permissions";
import { MODULES } from "@/modules/registry";
import { ForbiddenPage, NotFoundPage } from "@/pages/errors/ErrorPages";
import { Skeleton } from "@/ui";

const LoginPage = lazy(() => import("@/pages/auth/LoginPage"));
const RegisterPage = lazy(() => import("@/pages/auth/RegisterPage"));
const AuthCallbackPage = lazy(() => import("@/pages/auth/AuthCallbackPage"));
const InvitePage = lazy(() => import("@/pages/auth/InvitePage"));
const ForgotPasswordPage = lazy(() => import("@/pages/auth/ForgotPasswordPage"));
const ResetPasswordPage = lazy(() => import("@/pages/auth/ResetPasswordPage"));
const VerifyEmailPage = lazy(() => import("@/pages/auth/VerifyEmailPage"));
const OrgPage = lazy(() => import("@/pages/org/OrgPage"));
const TenantsPage = lazy(() => import("@/pages/sa/TenantsPage"));
const MailOutboxPage = lazy(() => import("@/pages/sa/MailOutboxPage"));
const AssistantPage = lazy(() => import("@/pages/assistant/AssistantPage"));
const OverviewPage = lazy(() => import("@/pages/overview/OverviewPage"));
const ProfilePage = lazy(() => import("@/pages/profile/ProfilePage"));
const NotificationsPage = lazy(() => import("@/pages/notifications/NotificationsPage"));
const UsersPage = lazy(() => import("@/pages/admin/UsersPage"));
const RolesPage = lazy(() => import("@/pages/admin/RolesPage"));
const StatusPage = lazy(() => import("@/pages/sa/StatusPage"));
const EventsPage = lazy(() => import("@/pages/sa/EventsPage"));
const IssuesPage = lazy(() => import("@/pages/sa/IssuesPage"));
const SettingsPage = lazy(() => import("@/pages/sa/SettingsPage"));
const StudioPage = lazy(() => import("@/pages/studio/StudioPage"));
const TracesPage = lazy(() => import("@/pages/sa/TracesPage"));
const TraceDetail = lazy(() => import("@/pages/sa/TraceDetail"));
const UsagePage = lazy(() => import("@/pages/sa/UsagePage"));
const ChatGuardPage = lazy(() => import("@/pages/sa/ChatGuardPage"));
const AiSettingsPage = lazy(() => import("@/pages/sa/AiSettingsPage"));

function PageFallback() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

class RouteBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  // Error boundary cần class (React 19): một trang hỏng không làm sập khung.
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <NotFoundPage /> : this.props.children;
  }
}

const page = (title: string, subtitle: string | undefined, node: ReactNode) => (
  <Titled title={title} subtitle={subtitle}>
    <RouteBoundary>
      <Suspense fallback={<PageFallback />}>{node}</Suspense>
    </RouteBoundary>
  </Titled>
);
const bare = (node: ReactNode) => <Suspense fallback={null}>{node}</Suspense>;

/** Trang của module (registry — D25), có quyền thì bọc guard. */
const moduleRoutes: RouteObject[] = MODULES.flatMap((m) => m.routes ?? []).map((r) => {
  const route = { path: r.path, element: page(r.title, r.subtitle, <r.component />) };
  return r.perm ? { element: <RequirePermission permission={r.perm} />, children: [route] } : route;
});

export const routes: RouteObject[] = [
  { path: "/login", element: bare(<LoginPage />) },
  { path: "/register", element: bare(<RegisterPage />) },
  { path: "/auth/callback", element: bare(<AuthCallbackPage />) },
  { path: "/invite/:token", element: bare(<InvitePage />) },
  { path: "/forgot-password", element: bare(<ForgotPasswordPage />) },
  { path: "/reset-password", element: bare(<ResetPasswordPage />) },
  { path: "/verify-email", element: bare(<VerifyEmailPage />) },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: page("nav.overview", "sub.overview", <OverviewPage />) },
          { path: "assistant", element: page("nav.assistant", "sub.assistant", <AssistantPage />) },
          { path: "notifications", element: page("nav.notifications", "sub.notifications", <NotificationsPage />) },
          { path: "profile", element: page("nav.profile", "sub.profile", <ProfilePage />) },
          { path: "org", element: page("nav.org", "sub.org", <OrgPage />) },
          ...moduleRoutes,
          { path: "403", element: page("page.forbidden", undefined, <ForbiddenPage />) },
          {
            element: <RequirePermission permission={PERMS.USER_VIEW} />,
            children: [{ path: "admin/users", element: page("nav.users", "sub.users", <UsersPage />) }],
          },
          {
            element: <RequirePermission permission={PERMS.USER_VIEW} />,
            children: [{ path: "admin/roles", element: page("nav.roles", "sub.roles", <RolesPage />) }],
          },
          {
            element: <RequireSuperadmin />,
            children: [
              { path: "sa/status", element: page("nav.status", "sub.status", <StatusPage />) },
              { path: "sa/events", element: page("nav.events", "sub.events", <EventsPage />) },
              { path: "sa/issues", element: page("nav.issues", "sub.issues", <IssuesPage />) },
              { path: "sa/settings", element: page("nav.settings", "sub.settings", <SettingsPage />) },
              { path: "sa/tenants", element: page("nav.tenants", "sub.tenants", <TenantsPage />) },
              { path: "sa/mail", element: page("nav.mail", "sub.mail", <MailOutboxPage />) },
              { path: "studio", element: page("nav.studio", "sub.studio", <StudioPage />) },
              { path: "sa/traces", element: page("nav.traces", "sub.traces", <TracesPage />) },
              { path: "sa/traces/:id", element: page("nav.traceDetail", "sub.traceDetail", <TraceDetail />) },
              { path: "sa/usage", element: page("nav.usage", "sub.usage", <UsagePage />) },
              { path: "sa/chat-guard", element: page("nav.chatGuard", "sub.chatGuard", <ChatGuardPage />) },
              { path: "sa/ai-settings", element: page("nav.aiSettings", "sub.aiSettings", <AiSettingsPage />) },
            ],
          },
          { path: "*", element: page("page.notFound", undefined, <NotFoundPage />) },
        ],
      },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
