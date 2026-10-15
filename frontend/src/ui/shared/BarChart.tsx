import { useState } from "react";

import { cn } from "@/lib/cn";

export type Bar = { label: string; value: number; tip?: string };

const H = 100;

/** Biểu đồ cột SVG tự dựng: co theo bề ngang khung (cột trong SVG co giãn, nhãn trục X là HTML nên không méo),
 *  nhãn thưa dần khi nhiều cột, chạm / rê chuột hiện giá trị cột. Không thư viện — đủ cho số liệu theo ngày / giờ. */
export function BarChart({ bars, format, className, testId }: { bars: Bar[]; format: (v: number) => string; className?: string; testId?: string }) {
  const [active, setActive] = useState<number | null>(null);
  const n = Math.max(bars.length, 1);
  const max = Math.max(...bars.map((b) => b.value), 0);
  const every = Math.max(1, Math.ceil(bars.length / 7));
  const shown = active != null ? bars[active] : null;
  return (
    <figure className={cn("grid min-w-0 gap-1", className)} data-testid={testId}>
      <div className="h-5 truncate text-xs text-muted-foreground" aria-live="polite" data-testid={testId ? `${testId}-value` : undefined}>
        {shown ? `${shown.tip ?? shown.label}: ${format(shown.value)}` : `max ${format(max)}`}
      </div>
      <svg viewBox={`0 0 ${n * 10} ${H}`} preserveAspectRatio="none" className="h-40 w-full" role="img" aria-label={`${bars.length} cột, lớn nhất ${format(max)}`}>
        {bars.map((b, i) => {
          const h = max > 0 ? Math.max(b.value > 0 ? 1 : 0, ((H - 4) * b.value) / max) : 0;
          return (
            <g key={`${b.label}-${i}`}>
              <rect
                x={i * 10}
                y={0}
                width={10}
                height={H}
                fill="transparent"
                onMouseEnter={() => setActive(i)}
                onMouseLeave={() => setActive(null)}
                onClick={() => setActive(i)}
                data-testid={testId ? `${testId}-bar-${i}` : undefined}
              />
              <rect x={i * 10 + 1.5} y={H - h} width={7} height={h} className={cn("pointer-events-none", active === i ? "fill-primary" : "fill-primary/60")} />
            </g>
          );
        })}
      </svg>
      <div className="relative h-4 overflow-hidden border-t border-border">
        {bars.map((b, i) =>
          i % every === 0 ? (
            <span key={`${b.label}-${i}`} className="absolute top-0.5 -translate-x-1/2 whitespace-nowrap text-[10px] text-muted-foreground" style={{ left: `${((i + 0.5) / n) * 100}%` }}>
              {b.label}
            </span>
          ) : null,
        )}
      </div>
    </figure>
  );
}
