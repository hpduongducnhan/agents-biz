import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import { Toaster } from "sonner";

import { createAppRouter } from "@/boot/router";
import { queryClient } from "@/lib/query-client";
import { TooltipProvider } from "@/ui";

const router = createAppRouter();

/** Toast tô bằng token theme (sáng / tối tự đúng), không dùng bảng màu riêng của sonner. */
const toastClasses = {
  toast: "rounded-2xl! border-border! bg-popover! text-popover-foreground! shadow-card!",
  description: "text-muted-foreground!",
  error: "text-destructive!",
  success: "text-positive!",
};

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <RouterProvider router={router} />
      </TooltipProvider>
      <Toaster position="top-center" closeButton toastOptions={{ classNames: toastClasses }} />
    </QueryClientProvider>
  );
}
