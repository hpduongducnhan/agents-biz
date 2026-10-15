import { type SelectHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

/** <select> gốc — trên điện thoại mở bộ chọn của hệ điều hành; luôn `max-w-full` để không nở lưới cha. */
const NativeSelect = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(
      "h-11 w-full max-w-full rounded-xl border border-input bg-card px-3 text-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:h-10 md:text-sm",
      className,
    )}
    {...props}
  />
));
NativeSelect.displayName = "NativeSelect";

export { NativeSelect };
