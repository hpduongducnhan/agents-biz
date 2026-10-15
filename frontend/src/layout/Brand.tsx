import { cn } from "@/lib/cn";

/** Logo theo theme: bản thường trên nền sáng, bản -dark trên nền tối — CSS chọn qua .theme-*-only. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <>
      <img src="/brand/mark.svg" alt="BizWithAgents" className={cn("theme-light-only", className)} />
      <img src="/brand/mark-dark.svg" alt="" aria-hidden className={cn("theme-dark-only", className)} />
    </>
  );
}

export function BrandLockup({ className }: { className?: string }) {
  return (
    <>
      <img src="/brand/lockup.svg" alt="BizWithAgents" className={cn("theme-light-only", className)} />
      <img src="/brand/lockup-dark.svg" alt="" aria-hidden className={cn("theme-dark-only", className)} />
    </>
  );
}
