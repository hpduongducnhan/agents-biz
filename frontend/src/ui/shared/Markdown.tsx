/** Markdown tối giản cho câu trả lời của trợ lý — dựng thẳng React node (không `innerHTML`, FE rule 8): đoạn, xuống
 *  dòng, tiêu đề `#`…`######`, danh sách `-` / `*` / `•` / `1.` lồng nhau theo thụt đầu dòng (giữ số bắt đầu), trích
 *  dẫn `>`, vạch ngăn `---`, **đậm**, *nghiêng*, `code`, link http(s). Thứ khác hiện nguyên chữ. */
import { Fragment, type ReactNode } from "react";

import { cn } from "@/lib/cn";

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
const ITEM = /^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return (
        <code key={k} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]">
          {part.slice(1, -1)}
        </code>
      );
    const link = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(part);
    if (link)
      return (
        <a key={k} href={link[2]} target="_blank" rel="noopener noreferrer" className="text-brand underline underline-offset-2">
          {link[1]}
        </a>
      );
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={k}>{part.slice(1, -1)}</em>;
    return <Fragment key={k}>{part}</Fragment>;
  });
}

function lines(text: string, key: string): ReactNode[] {
  return text.split("\n").flatMap((line, i) => (i ? [<br key={`${key}-br${i}`} />, ...inline(line, `${key}-${i}`)] : inline(line, `${key}-${i}`)));
}

type Item = { text: string; children: List[] };
type List = { kind: "ul" | "ol"; start: number; indent: number; items: Item[] };
type Node = { kind: "p"; text: string } | { kind: "quote"; text: string } | { kind: "h"; level: number; text: string } | { kind: "hr" } | { kind: "list"; list: List };

/** Dòng → khối. Danh sách mở theo chồng thụt đầu dòng: sâu hơn mục trước = danh sách con của mục đó; dòng thụt vào
 *  không phải mục = nối tiếp mục cuối (kể cả sau một dòng trống). */
export function parse(source: string): Node[] {
  const out: Node[] = [];
  const stack: List[] = [];
  let para: string[] = [];
  let quote: string[] = [];
  let blank = false;
  const flush = () => {
    if (para.length) out.push({ kind: "p", text: para.join("\n") });
    if (quote.length) out.push({ kind: "quote", text: quote.join("\n") });
    para = [];
    quote = [];
  };
  const closeLists = () => {
    stack.length = 0;
  };
  for (const raw of source.replace(/\r\n/g, "\n").replace(/\t/g, "    ").split("\n")) {
    if (!raw.trim()) {
      flush();
      blank = true;
      continue;
    }
    const item = ITEM.exec(raw);
    if (item && !RULE.test(raw)) {
      flush();
      const indent = item[1]?.length ?? 0;
      const marker = item[2] ?? "-";
      const kind = /\d/.test(marker) ? "ol" : "ul";
      while (stack.length && (stack.at(-1)?.indent ?? 0) > indent) stack.pop();
      let top = stack.at(-1);
      if (top && top.indent === indent && top.kind !== kind) {
        stack.pop();
        top = undefined;
      }
      if (!top || top.indent < indent) {
        const list: List = { kind, start: kind === "ol" ? Number.parseInt(marker, 10) : 1, indent, items: [] };
        const parent = stack.at(-1)?.items.at(-1);
        if (parent && (stack.at(-1)?.indent ?? 0) < indent) parent.children.push(list);
        else out.push({ kind: "list", list });
        stack.push(list);
        top = list;
      }
      top.items.push({ text: item[3] ?? "", children: [] });
      blank = false;
      continue;
    }
    const last = stack.at(-1)?.items.at(-1);
    if (last && /^\s/.test(raw)) {
      last.text += `\n${raw.trim()}`; // dòng thụt vào dưới mục → thuộc mục đó
      blank = false;
      continue;
    }
    closeLists();
    const heading = HEADING.exec(raw);
    if (heading) {
      flush();
      out.push({ kind: "h", level: heading[1]?.length ?? 1, text: heading[2] ?? "" });
    } else if (RULE.test(raw)) {
      flush();
      out.push({ kind: "hr" });
    } else if (QUOTE.test(raw)) {
      if (para.length) flush();
      quote.push(QUOTE.exec(raw)?.[1] ?? "");
    } else {
      if (quote.length || blank) flush();
      para.push(raw.trim());
    }
    blank = false;
  }
  flush();
  return out;
}

function ListView({ list, depth, k }: { list: List; depth: number; k: string }) {
  const items = list.items.map((it, j) => (
    <li key={j} className="pl-0.5">
      {lines(it.text, `${k}-${j}`)}
      {it.children.map((c, n) => (
        <ListView key={n} list={c} depth={depth + 1} k={`${k}-${j}-${n}`} />
      ))}
    </li>
  ));
  const cls = cn("space-y-1 pl-5", depth > 0 && "mt-1", list.kind === "ol" ? "list-decimal" : depth % 2 ? "list-[circle]" : "list-disc");
  return list.kind === "ol" ? (
    <ol start={list.start !== 1 ? list.start : undefined} className={cls}>
      {items}
    </ol>
  ) : (
    <ul className={cls}>{items}</ul>
  );
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("grid gap-2 break-words text-sm leading-relaxed", className)}>
      {parse(text).map((b, i) => {
        if (b.kind === "p") return <p key={i}>{lines(b.text, `p${i}`)}</p>;
        if (b.kind === "h")
          return (
            <p key={i} role="heading" aria-level={Math.min(b.level + 2, 6)} className={cn("font-bold", b.level <= 2 ? "mt-1 text-[0.95rem]" : "text-sm")}>
              {inline(b.text, `h${i}`)}
            </p>
          );
        if (b.kind === "hr") return <hr key={i} className="border-border" />;
        if (b.kind === "quote")
          return (
            <blockquote key={i} className="border-l-2 border-brand/40 pl-3 text-muted-foreground">
              {lines(b.text, `q${i}`)}
            </blockquote>
          );
        return <ListView key={i} list={b.list} depth={0} k={`l${i}`} />;
      })}
    </div>
  );
}
