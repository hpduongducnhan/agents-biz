import { UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { type InvitePreview, tenantApi } from "@/features/tenant/api";
import { useT } from "@/lib/i18n";
import { Skeleton } from "@/ui";

import { AuthLayout } from "./AuthLayout";
import { FormAlert } from "./FormAlert";
import { RegisterForm } from "./RegisterForm";

/** `/invite/:token` — xem trước lời mời (công khai) rồi đăng ký vào đúng tổ chức + vai trò (D12). Gọi preview một lần,
 * ngoài cache query: đăng nhập xong `resetQueries` sẽ tải lại mọi query đang mở — token dùng một lần lúc đó đã hết hiệu lực. */
export default function InvitePage() {
  const t = useT();
  const { token = "" } = useParams();
  const [{ data, isError }, setPreview] = useState<{ data?: InvitePreview; isError?: boolean }>({});
  useEffect(() => {
    let live = true;
    tenantApi.preview(token).then(
      (d) => live && setPreview({ data: d }),
      () => live && setPreview({ isError: true }),
    );
    return () => {
      live = false;
    };
  }, [token]);
  const isLoading = !data && !isError;

  return (
    <AuthLayout title={t("auth.invite.title")} subtitle={t("auth.register.subtitle")}>
      {isLoading && <Skeleton className="h-24 w-full" />}
      {isError && (
        <>
          <FormAlert text={t("auth.invite.invalid")} />
          <Link to="/login" className="block text-center font-bold text-brand">
            {t("auth.toLogin")}
          </Link>
        </>
      )}
      {data && (
        <>
          <div data-testid="invite-preview" className="flex items-start gap-3 rounded-xl bg-brand-muted p-3 text-sm">
            <UsersRound className="mt-0.5 h-5 w-5 shrink-0 text-brand" aria-hidden />
            <div className="min-w-0 space-y-0.5">
              <p className="font-bold">{t("auth.register.invited", { tenant: data.tenant_name, role: data.role_name })}</p>
              {data.email && <p className="text-muted-foreground">{t("auth.register.inviteFor", { email: data.email })}</p>}
            </div>
          </div>
          <RegisterForm next="/" inviteToken={token} />
        </>
      )}
    </AuthLayout>
  );
}
