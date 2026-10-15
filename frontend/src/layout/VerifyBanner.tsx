import { MailWarning } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { authApi } from "@/features/auth/api";
import { usePublicInfo } from "@/features/system/hooks";
import { useCurrentUser } from "@/lib/auth/permissions";
import { useT } from "@/lib/i18n";
import { Button } from "@/ui";

/** Nhắc xác thực email khi `email_verification` khác `off` và tài khoản chưa xác thực (D14) — gửi lại thư một lần. */
export function VerifyBanner() {
  const t = useT();
  const user = useCurrentUser();
  const { data: info } = usePublicInfo();
  const [sent, setSent] = useState(false);
  if (!user || user.email_verified || user.is_superadmin || !info || info.email_verification === "off") return null;
  const resend = async () => {
    await authApi.requestVerify(user.email).catch(() => undefined);
    setSent(true);
    toast.success(t("auth.verify.resent"));
  };
  return (
    <div role="status" data-testid="verify-banner" className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-warning/40 bg-warning/10 p-3 text-sm">
      <MailWarning className="h-4 w-4 shrink-0 text-warning" aria-hidden />
      <span className="min-w-0 flex-1">{t("verify.banner")}</span>
      <Button size="sm" variant="outline" disabled={sent} onClick={() => void resend()} data-testid="verify-banner-send">
        {t("verify.bannerSend")}
      </Button>
    </div>
  );
}
