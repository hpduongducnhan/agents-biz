import { Ban, Compass } from "lucide-react";
import { Link } from "react-router";

import { useT } from "@/lib/i18n";
import { Button, EmptyState } from "@/ui";

export function NotFoundPage() {
  const t = useT();
  return (
    <EmptyState
      className="py-24"
      icon={<Compass className="h-10 w-10" />}
      title={t("page.notFound")}
      description={t("page.notFoundDesc")}
      action={
        <Button asChild>
          <Link to="/">{t("page.home")}</Link>
        </Button>
      }
    />
  );
}

export function ForbiddenPage() {
  const t = useT();
  return (
    <div className="flex min-h-[60dvh] items-center justify-center" data-testid="page-forbidden">
      <EmptyState
        icon={<Ban className="h-10 w-10" />}
        title={t("page.forbidden")}
        description={t("page.forbiddenDesc")}
        action={
          <Button asChild>
            <Link to="/">{t("page.home")}</Link>
          </Button>
        }
      />
    </div>
  );
}
