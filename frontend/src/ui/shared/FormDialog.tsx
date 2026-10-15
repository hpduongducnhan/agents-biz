import { useT } from "@/lib/i18n";
import { Button } from "../button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../dialog";
import type { ReactNode } from "react";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  onSubmit: () => void;
  submitting?: boolean;
  disabled?: boolean;
  submitLabel?: string;
  wide?: boolean;
  /** Lỗi của lần gửi gần nhất — ở lại trong hộp thoại, cạnh chỗ cần sửa (toast tự tắt sau vài giây). */
  error?: string | null;
};

/** Hộp thoại form (tiêu đề + nội dung + Huỷ / Lưu) cho module — submit bằng Enter, nút lưu khoá khi đang gửi. */
export function FormDialog({ open, onOpenChange, title, children, onSubmit, submitting, disabled, submitLabel, wide, error }: Props) {
  const t = useT();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={wide ? "max-h-[90dvh] overflow-y-auto sm:max-w-3xl" : "max-h-[90dvh] overflow-y-auto"}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit();
          }}
        >
          {children}
          {error ? (
            <p role="alert" className="break-words text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={disabled || submitting} data-testid="dialog-submit">
              {submitLabel ?? t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
