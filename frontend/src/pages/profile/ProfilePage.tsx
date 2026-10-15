import { AlertTriangle } from "lucide-react";
import { useSearchParams } from "react-router";

import { useAuthStore } from "@/lib/auth/store";
import { useT } from "@/lib/i18n";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/ui";

import { InfoTab } from "./InfoTab";
import { PasswordTab, SessionsCard } from "./PasswordTab";

const TABS = ["info", "password", "sessions"] as const;
type Tab = (typeof TABS)[number];

export default function ProfilePage() {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const user = useAuthStore((s) => s.user);
  if (!user) return null;
  const forced = user.must_change_password;
  const tab: Tab = forced ? "password" : (TABS.find((x) => x === params.get("tab")) ?? "info");

  return (
    <div className="space-y-4">
      {forced && (
        <div role="alert" data-testid="force-change" className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          {t("profile.forceChange")}
        </div>
      )}
      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
        <TabsList className="grid w-full grid-cols-3 md:inline-flex md:w-auto">
          <TabsTrigger value="info" disabled={forced} data-testid="profile-tab-info">
            {t("profile.tab.info")}
          </TabsTrigger>
          <TabsTrigger value="password" data-testid="profile-tab-password">
            {t("profile.tab.password")}
          </TabsTrigger>
          <TabsTrigger value="sessions" disabled={forced} data-testid="profile-tab-sessions">
            {t("profile.tab.sessions")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="info" className="grid gap-4">
          <InfoTab user={user} />
        </TabsContent>
        <TabsContent value="password">
          <PasswordTab user={user} forced={forced} />
        </TabsContent>
        <TabsContent value="sessions">
          <SessionsCard />
        </TabsContent>
      </Tabs>
    </div>
  );
}
