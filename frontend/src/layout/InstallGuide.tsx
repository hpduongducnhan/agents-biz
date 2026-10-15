import { Download, EllipsisVertical, SquarePlus, Share, Smartphone, X } from "lucide-react";
import { useState } from "react";

import { useT } from "@/lib/i18n";
import { installPwa, isStandalone, platformOf, usePwaStore } from "@/lib/pwa";
import { useUiStore } from "@/stores/ui.store";
import { Button, Card, Sheet, Tabs, TabsContent, TabsList, TabsTrigger } from "@/ui";

type Step = { icon: typeof Share; key: string };

const IOS: Step[] = [
  { icon: Smartphone, key: "pwa.ios.1" },
  { icon: Share, key: "pwa.ios.2" },
  { icon: SquarePlus, key: "pwa.ios.3" },
  { icon: Download, key: "pwa.ios.4" },
];
const ANDROID: Step[] = [
  { icon: EllipsisVertical, key: "pwa.android.1" },
  { icon: SquarePlus, key: "pwa.android.2" },
  { icon: Download, key: "pwa.android.3" },
];

function Steps({ steps, testId }: { steps: Step[]; testId: string }) {
  const t = useT();
  return (
    <ol className="space-y-3" data-testid={testId}>
      {steps.map(({ icon: Icon, key }, i) => (
        <li key={key} className="flex gap-3">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-muted text-sm font-extrabold text-brand">{i + 1}</span>
          <span className="flex min-w-0 flex-1 items-start gap-2 pt-1 text-sm">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="break-words">{t(key)}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Hướng dẫn thêm BizWithAgents vào màn hình chính: tab iPhone / Android chọn sẵn theo máy; Android có nút cài ngay
 *  khi Chrome đã phát `beforeinstallprompt`. */
export function InstallGuide() {
  const t = useT();
  const open = useUiStore((s) => s.installGuideOpen);
  const setOpen = useUiStore((s) => s.setInstallGuide);
  const canInstall = usePwaStore((s) => !!s.prompt);
  const [tab, setTab] = useState<string>(() => (platformOf() === "android" ? "android" : "ios"));
  return (
    <Sheet open={open} onOpenChange={setOpen} title={t("pwa.guide.title")} description={t("pwa.guide.desc")} testId="install-guide">
      {isStandalone() ? (
        <p className="text-sm font-semibold" data-testid="install-standalone">
          {t("pwa.standalone")}
        </p>
      ) : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="w-full">
            <TabsTrigger value="ios" className="flex-1" data-testid="install-tab-ios">
              {t("pwa.guide.ios")}
            </TabsTrigger>
            <TabsTrigger value="android" className="flex-1" data-testid="install-tab-android">
              {t("pwa.guide.android")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="ios" className="mt-4 space-y-3">
            <Steps steps={IOS} testId="install-steps-ios" />
            <p className="rounded-xl bg-muted p-3 text-xs" data-testid="install-push-tip">
              {t("pwa.pushTip")}
            </p>
          </TabsContent>
          <TabsContent value="android" className="mt-4 space-y-4">
            {canInstall && (
              <div className="space-y-2 rounded-xl bg-brand-muted p-3">
                <p className="text-sm font-semibold">{t("pwa.android.now")}</p>
                <Button className="w-full" data-testid="install-now" onClick={() => void installPwa().then((ok) => ok && setOpen(false))}>
                  <Download className="h-4 w-4" />
                  {t("pwa.install")}
                </Button>
              </div>
            )}
            <Steps steps={ANDROID} testId="install-steps-android" />
            <p className="rounded-xl bg-muted p-3 text-xs">{t("pwa.pushTip")}</p>
          </TabsContent>
        </Tabs>
      )}
    </Sheet>
  );
}

/** Gợi ý ở đầu trang Tổng quan trên điện thoại — ẩn khi đã chạy như app hoặc người dùng tắt (nhớ trên máy). */
export function InstallHint() {
  const t = useT();
  const dismissed = useUiStore((s) => s.installHintDismissed);
  const dismiss = useUiStore((s) => s.dismissInstallHint);
  const openGuide = useUiStore((s) => s.setInstallGuide);
  if (dismissed || isStandalone()) return null;
  return (
    <Card className="flex items-start gap-3 p-3 md:hidden" data-testid="install-hint">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-brand-muted text-brand">
        <Smartphone className="h-5 w-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <div>
          <p className="text-sm font-bold">{t("pwa.hint.title")}</p>
          <p className="text-xs text-muted-foreground">{t("pwa.hint.body")}</p>
        </div>
        <Button size="sm" data-testid="install-hint-show" onClick={() => openGuide(true)}>
          {t("pwa.hint.show")}
        </Button>
      </div>
      <Button size="icon" variant="ghost" aria-label={t("pwa.hint.dismiss")} data-testid="install-hint-dismiss" onClick={dismiss}>
        <X className="h-4 w-4" />
      </Button>
    </Card>
  );
}
