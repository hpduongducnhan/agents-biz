// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "@/ui";
import { parse } from "@/ui/shared/Markdown";

describe("Markdown", () => {
  it("danh sách - và 1., **đậm**, *nghiêng*, `code`", () => {
    const { container } = render(<Markdown text={"- một\n- hai\n\n1. a\n2. b\n\n**đậm** và *nghiêng* và `x = 1`"} />);
    expect(container.querySelectorAll("ul > li")).toHaveLength(2);
    expect(container.querySelectorAll("ol > li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("đậm");
    expect(container.querySelector("em")?.textContent).toBe("nghiêng");
    expect(container.querySelector("code")?.textContent).toBe("x = 1");
  });

  it("link http(s) thành <a> mở tab mới, rel an toàn", () => {
    render(<Markdown text="xem [trang](https://example.com/a?b=1)" />);
    const a = screen.getByRole("link", { name: "trang" });
    expect(a.getAttribute("href")).toBe("https://example.com/a?b=1");
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("rel")).toContain("noopener");
  });

  it("link javascript: / data: không thành <a>, hiện nguyên chữ", () => {
    const { container } = render(<Markdown text="[bấm](javascript:alert(1)) và [d](data:text/html,x)" />);
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("[bấm](javascript:alert(1))");
  });

  it("<script> và <img onerror> hiện nguyên chữ, không tạo phần tử", () => {
    const { container } = render(<Markdown text={'<script>alert(1)</script>\n\n<img src=x onerror="alert(2)">'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.textContent).toContain('<img src=x onerror="alert(2)">');
  });
});

const PROD = `## Thiết lập một lần

1. Vào **Nhóm** → mở nhóm.
2. Chờ tài khoản **Lan** chấp nhận.
3. Ghi **một khoản chi**, gồm:
   - Ví: **Quỹ cơm SCC**
   - Số tiền: giá món
4. Xong.`;

describe("Markdown", () => {
  it("tiêu đề thành role=heading, không còn ##", () => {
    const { container } = render(<Markdown text={"## Tiêu đề\n\nnội dung"} />);
    const h = screen.getByRole("heading", { name: "Tiêu đề" });
    expect(h.getAttribute("aria-level")).toBe("4");
    expect(container.textContent).not.toContain("##");
  });

  it("aria-level tối đa 6", () => {
    render(<Markdown text="###### nhỏ" />);
    expect(screen.getByRole("heading", { name: "nhỏ" }).getAttribute("aria-level")).toBe("6");
  });

  it("ví dụ thật: một ol 4 li, li 3 chứa ul 2 mục, Xong là li 4", () => {
    const { container } = render(<Markdown text={PROD} />);
    expect(container.querySelectorAll("ol")).toHaveLength(1);
    const lis = container.querySelectorAll(":scope > div > ol > li");
    expect(lis).toHaveLength(4);
    expect(lis[2]?.querySelectorAll(":scope > ul > li")).toHaveLength(2);
    expect(lis[3]?.textContent).toBe("Xong.");
    expect(container.querySelectorAll("ul")).toHaveLength(1);
    expect(container.textContent).not.toContain("##");
  });

  it("danh sách số bắt đầu từ 3 giữ start", () => {
    const { container } = render(<Markdown text={"3. ba\n4. bốn"} />);
    expect(container.querySelector("ol")?.getAttribute("start")).toBe("3");
    const one = render(<Markdown text={"1. a\n2. b"} />);
    expect(one.container.querySelector("ol")?.hasAttribute("start")).toBe(false);
  });

  it("lồng hai cấp bằng thụt 2 dấu cách, ul xen kẽ disc / circle", () => {
    const { container } = render(<Markdown text={"- a\n  - b\n    - c\n- d"} />);
    const top = container.querySelector(":scope > div > ul");
    expect(top?.querySelectorAll(":scope > li")).toHaveLength(2);
    const mid = top?.querySelector(":scope > li > ul");
    expect(mid?.querySelectorAll(":scope > li")).toHaveLength(1);
    const inner = mid?.querySelector(":scope > li > ul");
    expect(inner?.textContent).toBe("c");
    expect(top?.className).toContain("list-disc");
    expect(mid?.className).toContain("list-[circle]");
    expect(inner?.className).toContain("list-disc");
  });

  it("- rồi 1. cùng mức thụt thành hai danh sách anh em", () => {
    const { container } = render(<Markdown text={"- a\n- b\n1. x\n2. y"} />);
    expect(container.querySelectorAll("ul")).toHaveLength(1);
    expect(container.querySelectorAll("ol")).toHaveLength(1);
    expect(container.querySelector("ul")?.parentElement).toBe(container.querySelector("ol")?.parentElement);
  });

  it("dòng thụt dưới mục nối vào mục đó bằng <br>", () => {
    const { container } = render(<Markdown text={"- một\n  tiếp theo\n- hai"} />);
    const lis = container.querySelectorAll("li");
    expect(lis).toHaveLength(2);
    expect(lis[0]?.querySelector("br")).not.toBeNull();
    expect(lis[0]?.textContent).toBe("mộttiếp theo");
  });

  it("dòng trống giữa các mục vẫn một danh sách", () => {
    const { container } = render(<Markdown text={"1. a\n\n2. b\n\n3. c"} />);
    expect(container.querySelectorAll("ol")).toHaveLength(1);
    expect(container.querySelectorAll("li")).toHaveLength(3);
  });

  it("trích dẫn > và vạch ngăn", () => {
    const { container } = render(<Markdown text={"> lời trích\n> dòng hai\n\n---\n\nhết"} />);
    expect(container.querySelector("blockquote")?.textContent).toBe("lời tríchdòng hai");
    expect(container.querySelector("blockquote br")).not.toBeNull();
    expect(container.querySelector("hr")).not.toBeNull();
  });

  it("đoạn nhiều dòng giữ <br>, emoji giữ nguyên", () => {
    const { container } = render(<Markdown text={"Dạ em chưa làm xong 😥\nthử lại nhé 🙏"} />);
    expect(container.querySelectorAll("p")).toHaveLength(1);
    expect(container.querySelector("p br")).not.toBeNull();
    expect(container.textContent).toContain("😥");
    expect(container.textContent).toContain("🙏");
  });

  it("<script> trong mục danh sách vẫn là chữ", () => {
    const { container } = render(<Markdown text={"- <script>alert(1)</script>"} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("li")?.textContent).toBe("<script>alert(1)</script>");
  });

  it("parse(): cấu trúc ví dụ thật", () => {
    const nodes = parse(PROD);
    expect(nodes.map((n) => n.kind)).toEqual(["h", "list"]);
    expect(nodes[0]).toEqual({ kind: "h", level: 2, text: "Thiết lập một lần" });
    const list = nodes[1];
    if (list?.kind !== "list") throw new Error("không phải list");
    expect(list.list.kind).toBe("ol");
    expect(list.list.start).toBe(1);
    expect(list.list.items).toHaveLength(4);
    const third = list.list.items[2];
    expect(third?.children).toHaveLength(1);
    expect(third?.children[0]?.kind).toBe("ul");
    expect(third?.children[0]?.items.map((i) => i.text)).toEqual(["Ví: **Quỹ cơm SCC**", "Số tiền: giá món"]);
    expect(list.list.items[3]).toEqual({ text: "Xong.", children: [] });
  });

  it("parse(): p, quote, hr, tiêu đề, danh sách số bắt đầu 5", () => {
    expect(parse("a\nb\n\n> q\n\n***\n\n### H\n\n5. x")).toEqual([
      { kind: "p", text: "a\nb" },
      { kind: "quote", text: "q" },
      { kind: "hr" },
      { kind: "h", level: 3, text: "H" },
      { kind: "list", list: { kind: "ol", start: 5, indent: 0, items: [{ text: "x", children: [] }] } },
    ]);
  });
});
