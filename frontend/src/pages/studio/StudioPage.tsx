import { useState } from "react";
import { useSearchParams } from "react-router";

import { useT } from "@/lib/i18n";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/ui";

import { AgentsTab } from "./AgentsTab";
import { StudioActionsSlot } from "./common";
import { CredentialsTab } from "./CredentialsTab";
import { ModelsTab } from "./ModelsTab";
import { PersonaTab } from "./PersonaTab";
import { ProvidersTab } from "./ProvidersTab";

const TABS = ["agents", "providers", "credentials", "models", "persona"] as const;
type Tab = (typeof TABS)[number];

/** Agent Studio (superadmin — D22): agent, provider, key mã hoá, model + giá, persona chung. `?tab=` `?agent=`. */
export default function StudioPage() {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const tab: Tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "agents";
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  return (
    <StudioActionsSlot value={slot}>
      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })} className="grid gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="-mx-4 w-[calc(100%+2rem)] overflow-x-auto px-4 sm:mx-0 sm:w-auto sm:px-0">
            <TabsList className="w-max">
              {TABS.map((x) => (
                <TabsTrigger key={x} value={x} data-testid={`studio-tab-${x}`}>
                  {t(`studio.tab.${x}`)}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
          <div ref={setSlot} className="ml-auto flex w-full flex-wrap items-center justify-end gap-2 empty:hidden *:flex-1 sm:w-auto sm:*:flex-none" data-testid="studio-actions" />
        </div>
        <TabsContent value="agents">
          <AgentsTab />
        </TabsContent>
        <TabsContent value="providers">
          <ProvidersTab />
        </TabsContent>
        <TabsContent value="credentials">
          <CredentialsTab />
        </TabsContent>
        <TabsContent value="models">
          <ModelsTab />
        </TabsContent>
        <TabsContent value="persona">
          <PersonaTab />
        </TabsContent>
      </Tabs>
    </StudioActionsSlot>
  );
}
