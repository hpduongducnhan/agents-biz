/** Bảng thuần theo ui-system §4 (mặc định Table; DataTable chỉ khi cần sort / resize). */
import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function Table({ head, children, className }: { head: ReactNode[]; children: ReactNode; className?: string }) {
  return (
    <div className={cn("relative overflow-x-auto rounded-2xl border border-border bg-card", className)}>
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-4 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({ children, onClick, className, testId }: { children: ReactNode; onClick?: () => void; className?: string; testId?: string }) {
  return (
    <tr data-testid={testId} onClick={onClick} className={cn("border-t border-border transition-colors hover:bg-muted/40", onClick && "cursor-pointer", className)}>
      {children}
    </tr>
  );
}

export function Cell({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cn("px-4 py-2 align-middle", className)}>{children}</td>;
}
