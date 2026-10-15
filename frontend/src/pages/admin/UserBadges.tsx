import { ShieldCheck } from "lucide-react";

import type { AdminUser } from "@/features/admin/api";
import { useT } from "@/lib/i18n";
import { Badge } from "@/ui";

export function UserBadges({ user }: { user: AdminUser }) {
  const t = useT();
  return (
    <div className="flex flex-wrap gap-1">
      {user.is_superadmin && (
        <Badge className="gap-1" data-testid="user-badge-superadmin">
          <ShieldCheck className="h-3 w-3" />
          {t("nav.superadmin")}
        </Badge>
      )}
      {!user.is_active && <Badge variant="destructive">{t("admin.users.disabled")}</Badge>}
      {user.must_change_password && <Badge variant="outline">{t("admin.users.mustChange")}</Badge>}
      {user.is_active && !user.is_superadmin && !user.must_change_password && <Badge variant="secondary">{t("admin.users.activeBadge")}</Badge>}
    </div>
  );
}
