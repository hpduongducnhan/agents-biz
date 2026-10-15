import { Send, Square } from "lucide-react";
import { type ReactNode, useState } from "react";

import { useT } from "@/lib/i18n";
import { Button, Label, Textarea } from "@/ui";

type Props = { running: boolean; disabled?: boolean; leading?: ReactNode; onSend: (text: string) => boolean | Promise<boolean>; onStop: () => void };

/** Ô nhập ở đáy khung chat: Enter gửi, Shift+Enter xuống dòng; đang chạy → nút Dừng. Chữ 16px (không zoom iOS).
 *  Không bọc `<form>` + tắt autocomplete: iOS / Android không hiện thanh tự điền thẻ, địa chỉ, vị trí trên bàn phím. */
export function Composer({ running, disabled, leading, onSend, onStop }: Props) {
  const t = useT();
  const [text, setText] = useState("");
  const submit = async () => {
    const content = text.trim();
    if (!content || running || disabled) return;
    setText("");
    if (!(await onSend(content))) setText(content);
  };
  return (
    <div className="flex shrink-0 items-end gap-2 border-t border-border bg-background pt-3" data-testid="chat-composer">
      {leading}
      <Label htmlFor="chat-input" className="sr-only">
        {t("chat.input")}
      </Label>
      <Textarea
        id="chat-input"
        name="bw-chat-message"
        data-testid="chat-input"
        rows={1}
        autoComplete="off"
        autoCorrect="on"
        autoCapitalize="sentences"
        spellCheck
        inputMode="text"
        enterKeyHint="send"
        aria-autocomplete="none"
        data-form-type="other"
        data-lpignore="true"
        data-1p-ignore
        className="max-h-40 min-h-11 flex-1 resize-none text-base md:text-sm"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            void submit();
          }
        }}
        placeholder={t("chat.placeholder")}
        maxLength={8000}
        disabled={disabled}
      />
      {running ? (
        <Button type="button" variant="outline" size="icon" onClick={onStop} aria-label={t("chat.stop")} data-testid="chat-stop">
          <Square className="h-4 w-4" />
        </Button>
      ) : (
        <Button type="button" size="icon" disabled={!text.trim() || disabled} aria-label={t("chat.send")} data-testid="chat-send" onClick={() => void submit()}>
          <Send className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
