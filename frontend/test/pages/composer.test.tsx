// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/pages/assistant/Composer";

const setup = (onSend = vi.fn().mockResolvedValue(true)) => {
  render(<Composer running={false} onSend={onSend} onStop={vi.fn()} />);
  return {
    onSend,
    input: screen.getByTestId("chat-input") as HTMLTextAreaElement,
  };
};

describe("Composer (không form, tắt tự điền)", () => {
  it("không có <form>; ô nhập mang các thuộc tính chống tự điền", () => {
    const { input } = setup();
    expect(document.querySelector("form")).toBeNull();
    expect(screen.getByTestId("chat-composer").tagName).toBe("DIV");
    expect(input.closest("form")).toBeNull();
    expect(input.getAttribute("autocomplete")).toBe("off");
    expect(input.getAttribute("name")).toBe("bw-chat-message");
    expect(input.getAttribute("enterkeyhint")).toBe("send");
    expect(input.getAttribute("inputmode")).toBe("text");
    expect(input.getAttribute("aria-autocomplete")).toBe("none");
    expect(input.getAttribute("data-form-type")).toBe("other");
  });

  it("Enter gửi (đã trim) và xoá ô", async () => {
    const { input, onSend } = setup();
    await userEvent.setup().type(input, "  xin chào {Enter}");
    expect(onSend).toHaveBeenCalledWith("xin chào");
    expect(input.value).toBe("");
  });

  it("Shift+Enter xuống dòng, không gửi", async () => {
    const { input, onSend } = setup();
    await userEvent.setup().type(input, "a{Shift>}{Enter}{/Shift}b");
    expect(onSend).not.toHaveBeenCalled();
    expect(input.value).toBe("a\nb");
  });

  it("bấm nút gửi (type=button) gửi tin; trống thì nút bị khoá", async () => {
    const { input, onSend } = setup();
    const send = screen.getByTestId("chat-send") as HTMLButtonElement;
    expect(send.type).toBe("button");
    expect(send.disabled).toBe(true);
    await userEvent.setup().type(input, "hi");
    await userEvent.setup().click(send);
    expect(onSend).toHaveBeenCalledWith("hi");
  });

  it("gửi thất bại → giữ lại nội dung; đang chạy → hiện nút Dừng", async () => {
    const { input } = setup(vi.fn().mockResolvedValue(false));
    await userEvent.setup().type(input, "lỗi{Enter}");
    expect(input.value).toBe("lỗi");
    const stop = vi.fn();
    render(<Composer running onSend={vi.fn()} onStop={stop} />);
    await userEvent.setup().click(screen.getByTestId("chat-stop"));
    expect(stop).toHaveBeenCalledOnce();
  });
});
