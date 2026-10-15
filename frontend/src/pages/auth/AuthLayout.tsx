import type { ReactNode } from "react";

import { BrandLockup } from "@/layout/Brand";

/** Trang ngoài AppShell: một cột ưu tiên điện thoại, logo trên cùng. */
export function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <main className="flex min-h-dvh justify-center bg-background px-4 py-10 sm:items-center">
      <div className="w-full max-w-sm">
        <div className="flex justify-center">
          <BrandLockup className="h-12" />
        </div>
        <h1 className="mt-8 text-2xl font-extrabold">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        <div className="mt-6 space-y-4">{children}</div>
      </div>
    </main>
  );
}
