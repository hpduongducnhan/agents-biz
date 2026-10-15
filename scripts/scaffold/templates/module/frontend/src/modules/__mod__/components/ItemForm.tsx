import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useHasPermission } from "@/lib/auth/permissions";
import { useT } from "@/lib/i18n";
import { errorText, toastError } from "@/lib/query-client";
import { Button, ConfirmDialog, Field, FormDialog, Input, NativeSelect, Textarea } from "@/ui";

import { type __Mod__Item, __mod__Api } from "../api";
import { __MOD__ } from "../keys";
import { __MOD___PERMS } from "../perms";

type Props = { open: boolean; onOpenChange: (open: boolean) => void; item?: __Mod__Item | null };

/** Tạo (không có `item`) hoặc sửa một mục; sửa thì có nút xoá (quyền xoá, có xác nhận). */
export function ItemForm({ open, onOpenChange, item }: Props) {
  const t = useT();
  const qc = useQueryClient();
  const canEdit = useHasPermission(__MOD___PERMS.EDIT);
  const canDelete = useHasPermission(__MOD___PERMS.DELETE);
  const [title, setTitle] = useState(item?.title ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [status, setStatus] = useState(item?.status ?? "open");
  const [confirming, setConfirming] = useState(false);
  const done = (message: string) => {
    void qc.invalidateQueries({ queryKey: __MOD__.all });
    toast.success(t(message));
    onOpenChange(false);
  };
  const save = useMutation({
    mutationFn: () =>
      item
        ? __mod__Api.update({ item_id: item.id, title: title.trim(), description, status })
        : __mod__Api.create({ title: title.trim(), description }),
    onSuccess: () => done(item ? "__mod__.saved" : "__mod__.created"),
  });
  const remove = useMutation({
    mutationFn: () => __mod__Api.remove(item?.id ?? ""),
    onSuccess: () => {
      setConfirming(false);
      done("__mod__.deleted");
    },
    onError: (err) => toastError(err),
  });

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t(item ? "__mod__.edit" : "__mod__.new")}
      onSubmit={() => save.mutate()}
      submitting={save.isPending}
      disabled={!canEdit || !title.trim()}
      error={save.error ? errorText(save.error) : undefined}
    >
      <Field id="__mod__-title" label={t("__mod__.field.title")}>
        <Input id="__mod__-title" autoFocus maxLength={200} value={title} disabled={!canEdit} onChange={(e) => setTitle(e.target.value)} data-testid="__mod__-form-title" />
      </Field>
      <Field id="__mod__-desc" label={t("__mod__.field.description")}>
        <Textarea id="__mod__-desc" rows={4} maxLength={10000} value={description} disabled={!canEdit} onChange={(e) => setDescription(e.target.value)} data-testid="__mod__-form-description" />
      </Field>
      {item && (
        <Field id="__mod__-status" label={t("__mod__.field.status")}>
          <NativeSelect id="__mod__-status" value={status} disabled={!canEdit} onChange={(e) => setStatus(e.target.value as typeof status)} data-testid="__mod__-form-status">
            <option value="open">{t("__mod__.status.open")}</option>
            <option value="done">{t("__mod__.status.done")}</option>
          </NativeSelect>
        </Field>
      )}
      {item && canDelete && (
        <Button type="button" variant="ghost" className="justify-self-start text-destructive" onClick={() => setConfirming(true)} data-testid="__mod__-delete">
          <Trash2 className="h-4 w-4" />
          {t("__mod__.delete")}
        </Button>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("__mod__.delete")}
        description={t("__mod__.deleteConfirm", { title: item?.title ?? "" })}
        confirmLabel={t("__mod__.delete")}
        destructive
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </FormDialog>
  );
}
