import { useQuery } from "@tanstack/react-query";

import { useT } from "@/lib/i18n";
import { NativeSelect } from "@/ui";

import { tasksApi } from "../api";
import { TASKS } from "../keys";

const Q = { limit: 100 };

/** Chọn người làm trong tổ chức ("" = chưa giao). */
export function PeopleSelect(props: { id: string; value: string; onChange: (id: string) => void; disabled?: boolean; testId?: string }) {
  const t = useT();
  const { data } = useQuery({ queryKey: TASKS.people(Q), queryFn: () => tasksApi.people(Q), staleTime: 60_000 });
  return (
    <NativeSelect id={props.id} value={props.value} disabled={props.disabled} onChange={(e) => props.onChange(e.target.value)} data-testid={props.testId}>
      <option value="">{t("tasks.unassigned")}</option>
      {(data ?? []).map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </NativeSelect>
  );
}
