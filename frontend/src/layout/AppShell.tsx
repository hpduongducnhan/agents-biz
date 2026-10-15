import { useEffect } from "react";
import { Outlet, useLocation } from "react-router";

import { useCoreRealtime } from "@/boot/realtime";
import { cn } from "@/lib/cn";
import { syncPush } from "@/lib/push";
import { PageHeaderProvider } from "@/ui";

import { Header } from "./Header";
import { InstallGuide } from "./InstallGuide";
import { MobileDock } from "./MobileDock";
import { Sidebar } from "./Sidebar";
import { VerifyBanner } from "./VerifyBanner";

export function AppShell() {
  useCoreRealtime();
  useEffect(() => {
    void syncPush(); // đã cho phép thông báo → gắn đăng ký của máy với tài khoản đang đăng nhập
  }, []);
  const chat = useLocation().pathname.startsWith("/assistant"); // trang Trợ lý: không có cụm nút nổi ở đáy
  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <Sidebar />
      <PageHeaderProvider>
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Header />
          <main
            className={cn(
              "min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 md:pb-6",
              chat ? "pb-[calc(1rem+env(safe-area-inset-bottom))]" : "pb-[calc(5.5rem+env(safe-area-inset-bottom))]",
            )}
          >
            <VerifyBanner />
            <Outlet />
          </main>
        </div>
      </PageHeaderProvider>
      <MobileDock />
      <InstallGuide />
    </div>
  );
}
