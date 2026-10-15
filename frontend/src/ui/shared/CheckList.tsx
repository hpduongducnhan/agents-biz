/** Chọn nhiều (role, thành viên, quyền) bằng checkbox — dùng trong dialog gán. */
import { Checkbox } from "../checkbox";
import { Label } from "../label";

export type CheckItem = { id: string; label: string; hint?: string; disabled?: boolean };

export function CheckList({ items, value, onChange }: { items: CheckItem[]; value: string[]; onChange: (v: string[]) => void }) {
  const set = new Set(value);
  return (
    <div className="max-h-80 space-y-1 overflow-y-auto pr-1">
      {items.map((it) => (
        <label key={it.id} className="flex cursor-pointer items-start gap-3 rounded-md px-2 py-1.5 hover:bg-muted/50">
          <Checkbox
            checked={set.has(it.id)}
            disabled={it.disabled}
            onCheckedChange={(c) => onChange(c ? [...set, it.id] : [...set].filter((x) => x !== it.id))}
            aria-label={it.label}
          />
          <span className="min-w-0">
            <Label className="cursor-pointer text-sm">{it.label}</Label>
            {it.hint ? <span className="block text-xs text-muted-foreground">{it.hint}</span> : null}
          </span>
        </label>
      ))}
    </div>
  );
}
