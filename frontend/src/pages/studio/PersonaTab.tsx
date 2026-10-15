import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { studioApi } from "@/features/agent/api";
import { STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Button, Field, Skeleton, Textarea } from "@/ui";

import { useStudioMutation } from "./common";

function PersonaForm({ initial }: { initial: string }) {
  const t = useT();
  const [content, setContent] = useState(initial);
  const save = useStudioMutation(studioApi.savePersona, [STUDIO.persona()]);
  return (
    <div className="grid gap-3">
      <Field id="persona" label={t("studio.tab.persona")} hint={t("studio.persona.hint")}>
        <Textarea id="persona" rows={14} className="font-mono text-xs" value={content} maxLength={20000} onChange={(e) => setContent(e.target.value)} />
      </Field>
      <Button className="w-fit" disabled={save.isPending} onClick={() => save.mutate({ content })} data-testid="persona-save">
        {t("studio.save")}
      </Button>
    </div>
  );
}

export function PersonaTab() {
  const { data, isLoading } = useQuery({ queryKey: STUDIO.persona(), queryFn: studioApi.persona });
  if (isLoading || !data) return <Skeleton className="h-64 w-full" />;
  return <PersonaForm initial={data.content} />;
}
