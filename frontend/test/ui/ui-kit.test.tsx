// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  Button,
  Cell,
  CheckList,
  ConfirmDialog,
  CopyableId,
  EmptyState,
  FormDialog,
  Input,
  Row,
  ServerPagination,
  Sheet,
  Table,
  TooltipProvider,
  TruncText,
} from "@/ui";

const wrap = (node: ReactNode) => render(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>);
const classes = (el: Element) => el.className.split(/\s+/);

describe("primitive — ưu tiên điện thoại", () => {
  it("nút và ô nhập cao ≥ 44px dưới md, chữ ô nhập 16px dưới md (iOS không zoom)", () => {
    wrap(
      <>
        <Button>Lưu</Button>
        <Button size="icon" aria-label="Mở">
          +
        </Button>
        <Input aria-label="Tên" />
      </>,
    );
    expect(classes(screen.getByText("Lưu"))).toEqual(expect.arrayContaining(["h-11", "md:h-10"]));
    expect(classes(screen.getByLabelText("Mở"))).toEqual(expect.arrayContaining(["h-11", "w-11", "md:h-9"]));
    expect(classes(screen.getByLabelText("Tên"))).toEqual(expect.arrayContaining(["h-11", "text-base", "md:text-sm"]));
  });

  it("Sheet: trượt từ đáy dưới md, hộp giữa từ md; Esc đóng", async () => {
    const onOpenChange = vi.fn();
    wrap(
      <Sheet open onOpenChange={onOpenChange} title="Ghi nhanh" description="Sắp có" testId="sheet">
        <p>nội dung</p>
      </Sheet>,
    );
    const sheet = screen.getByTestId("sheet");
    expect(screen.getByRole("dialog", { name: "Ghi nhanh" })).toBe(sheet);
    expect(classes(sheet)).toEqual(expect.arrayContaining(["bottom-0", "rounded-t-3xl", "max-h-[90dvh]", "md:max-w-md"]));
    await userEvent.setup().keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("shared", () => {
  it("ConfirmDialog + FormDialog: nút theo ngôn ngữ, lỗi hiện trong hộp thoại", async () => {
    const onConfirm = vi.fn();
    const onSubmit = vi.fn();
    const view = wrap(<ConfirmDialog open onOpenChange={() => {}} title="Xoá?" onConfirm={onConfirm} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Xác nhận" }));
    expect(onConfirm).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Huỷ" })).toBeTruthy();
    view.unmount();
    wrap(
      <FormDialog open onOpenChange={() => {}} title="Sửa" onSubmit={onSubmit} error="Sai rồi">
        <Input aria-label="x" />
      </FormDialog>,
    );
    expect(screen.getByRole("alert").textContent).toBe("Sai rồi");
    fireEvent.click(screen.getByTestId("dialog-submit"));
    expect(onSubmit).toHaveBeenCalled();
  });

  it("ServerPagination: ẩn khi vừa một trang; số thẳng cột; bấm sau → offset kế", async () => {
    const onChange = vi.fn();
    const view = wrap(<ServerPagination offset={0} limit={20} total={20} onChange={onChange} />);
    expect(view.container.textContent).toBe("");
    view.unmount();
    wrap(<ServerPagination offset={0} limit={20} total={45} onChange={onChange} />);
    expect(screen.getByText("1–20 / 45")).toBeTruthy();
    await userEvent.setup().click(screen.getByLabelText("Trang sau"));
    expect(onChange).toHaveBeenCalledWith(20);
  });

  it("EmptyState, Table (khung cuộn có relative), CheckList", async () => {
    const onChange = vi.fn();
    wrap(
      <>
        <EmptyState title="Trống" description="Chưa có gì" action={<Button>Tạo</Button>} />
        <Table head={["Tên"]}>
          <Row testId="r1">
            <Cell className="max-w-[200px]">A</Cell>
          </Row>
        </Table>
        <CheckList items={[{ id: "a", label: "Quyền A" }]} value={[]} onChange={onChange} />
      </>,
    );
    expect(screen.getByText("Chưa có gì")).toBeTruthy();
    const frame = screen.getByTestId("r1").closest("table")?.parentElement as HTMLElement;
    expect(classes(frame)).toEqual(expect.arrayContaining(["relative", "overflow-x-auto"]));
    await userEvent.setup().click(screen.getByLabelText("Quyền A"));
    expect(onChange).toHaveBeenCalledWith(["a"]);
  });

  it("TruncText: cắt một dòng, không dùng title, hover hiện đủ bằng Tooltip (R16)", async () => {
    const full = "Nguyễn Thị Phương Thảo Hoàng Ngọc Bích — tên rất dài để thử cắt chữ";
    wrap(<TruncText text={full} />);
    const span = screen.getByText(full);
    expect(classes(span)).toEqual(expect.arrayContaining(["block", "truncate"]));
    expect(span.hasAttribute("title")).toBe(false);
    await userEvent.setup().hover(span);
    expect((await screen.findByRole("tooltip")).textContent).toContain(full);
  });

  it("CopyableId: rút gọn, không title, bấm thì copy nguyên giá trị", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    wrap(<CopyableId value="0123456789abcdef" />);
    const btn = screen.getByRole("button", { name: "Sao chép" });
    expect(btn.textContent).toContain("01234567…");
    expect(btn.hasAttribute("title")).toBe(false);
    fireEvent.click(btn);
    expect(writeText).toHaveBeenCalledWith("0123456789abcdef");
  });
});
