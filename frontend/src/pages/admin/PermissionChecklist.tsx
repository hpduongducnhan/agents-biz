import { useMemo } from "react";

import type { Permission } from "@/features/rbac/api";
import { useT } from "@/lib/i18n";
import { Checkbox } from "@/ui";

type Props = { catalog: Permission[]; value: string[]; onChange: (v: string[]) => void; readOnly: boolean };

export function PermissionChecklist({ catalog, value, onChange, readOnly }: Props) {
  const t = useT();
  const groups = useMemo(() => {
    const byDomain = new Map<string, Permission[]>();
    for (const p of catalog) byDomain.set(p.domain, [...(byDomain.get(p.domain) ?? []), p]);
    return [...byDomain.entries()];
  }, [catalog]);
  const set = new Set(value);
  const toggle = (code: string, on: boolean) => onChange(on ? [...set, code] : [...set].filter((p) => p !== code));

  return (
    <div className="max-h-[45dvh] space-y-3 overflow-y-auto pr-1" data-testid="role-permissions">
      {groups.map(([domain, perms]) => {
        const codes = perms.map((p) => p.codename);
        const all = codes.every((c) => set.has(c));
        return (
          <section key={domain} className="rounded-xl border border-border">
            <label className="flex min-h-11 cursor-pointer items-center gap-3 border-b border-border bg-muted/50 px-3 text-xs font-bold uppercase tracking-wide md:min-h-9">
              <Checkbox
                checked={all}
                disabled={readOnly}
                aria-label={t("roles.allIn", { domain })}
                onCheckedChange={(c) => onChange(c ? [...new Set([...set, ...codes])] : [...set].filter((p) => !codes.includes(p)))}
              />
              {domain}
            </label>
            <div className="grid grid-cols-1 gap-1 p-2 sm:grid-cols-2">
              {perms.map((p) => (
                <label key={p.codename} className="flex min-h-11 cursor-pointer items-start gap-3 rounded-lg px-2 py-2 hover:bg-muted/50">
                  <Checkbox
                    checked={set.has(p.codename)}
                    disabled={readOnly}
                    aria-label={p.codename}
                    data-testid={`perm-${p.codename}`}
                    onCheckedChange={(c) => toggle(p.codename, !!c)}
                  />
                  <span className="min-w-0">
                    <span className="block break-all font-mono text-xs">{p.codename}</span>
                    {p.description ? <span className="block text-xs text-muted-foreground">{p.description}</span> : null}
                  </span>
                </label>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
