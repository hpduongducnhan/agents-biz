import { useState } from "react";

import { type Credential, credentialsApi, type Provider } from "@/features/agent/api";
import { CREDENTIALS, STUDIO } from "@/features/agent/keys";
import { useT } from "@/lib/i18n";
import { Field, FormDialog, Input, NativeSelect } from "@/ui";

import { useStudioMutation } from "./common";

type Props = { credential: Credential | null; providers: Provider[]; onClose: () => void };

export function CredentialDialog({ credential, providers, onClose }: Props) {
  const t = useT();
  const [name, setName] = useState(credential?.name ?? "");
  const [providerId, setProviderId] = useState(credential?.provider_id ?? "");
  const [secret, setSecret] = useState("");
  const [weight, setWeight] = useState(String(credential?.weight ?? 1));
  const [status, setStatus] = useState<"active" | "disabled">((credential?.status as "active" | "disabled") ?? "active");
  const keys = [CREDENTIALS.all, STUDIO.agents()];
  const create = useStudioMutation(credentialsApi.create, keys, onClose);
  const update = useStudioMutation(credentialsApi.update, keys, onClose);
  const w = Math.min(100, Math.max(1, Number(weight) || 1));
  const submit = () => {
    if (credential) {
      update.mutate({ credential_id: credential.id, name: name.trim(), weight: w, status, ...(secret ? { secret } : {}) });
    } else {
      create.mutate({ name: name.trim(), provider_id: providerId || null, secret, weight: w });
    }
  };
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={credential ? credential.name : t("studio.add")}
      submitting={create.isPending || update.isPending}
      disabled={!name.trim() || (!credential && !secret)}
      onSubmit={submit}
    >
      <Field id="cr-name" label={t("studio.name")}>
        <Input id="cr-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
      </Field>
      {!credential && (
        <Field id="cr-provider" label={t("studio.provider")}>
          <NativeSelect id="cr-provider" value={providerId} onChange={(e) => setProviderId(e.target.value)}>
            <option value="">{t("studio.noProvider")}</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
      )}
      <Field id="cr-secret" label={credential ? t("studio.secretReplace") : t("studio.secret")} hint={t("studio.secretHint")}>
        <Input id="cr-secret" type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)} data-testid="credential-secret" />
      </Field>
      <Field id="cr-weight" label={t("studio.weight")}>
        <Input id="cr-weight" type="number" inputMode="numeric" min={1} max={100} value={weight} onChange={(e) => setWeight(e.target.value)} />
      </Field>
      {credential && (
        <Field id="cr-status" label={t("studio.active")}>
          <NativeSelect id="cr-status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            <option value="active">{t("studio.status.active")}</option>
            <option value="disabled">{t("studio.status.disabled")}</option>
          </NativeSelect>
        </Field>
      )}
    </FormDialog>
  );
}
