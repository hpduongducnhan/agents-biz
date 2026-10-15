"""Đọc `.claude/**/*.md` thành dữ liệu trang: token, heading, link đã viết lại, trạng thái, menu domain."""

# ruff: noqa: E501 — khuôn HTML giữ mỗi thẻ trên một dòng cho dễ đọc

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from markdown_it import MarkdownIt
from markdown_it.token import Token

from docsite.common import (
    ASSETS,
    DOCS,
    REPO,
    SCHEME_RE,
    SEARCH_TEXT_CAP,
    SECTIONS,
    UPDATED_RE,
    VIEWBOX_RE,
    Doc,
    Domain,
    MenuRow,
    Rendered,
    _fence,
    _num,
    _plain,
    _rel,
    _task,
    canon_status,
    esc,
    slugify,
)
from docsite.diagrams import diagram_html, diagram_kind


class SiteParser:
    def __init__(self, root: Path = REPO) -> None:
        self.root = root.resolve()
        self.dir = self.root / DOCS
        self.md = self._markdown()
        self.docs: list[Doc] = []
        self.broken: list[tuple[str, str]] = []
        self._broken: set[tuple[str, str]] = set()
        self._ratios: dict[Path, tuple[str, str]] = {}

    # ── markdown ────────────────────────────────────────────────────────────
    def _markdown(self) -> MarkdownIt:
        md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
        md.add_render_rule("fence", _fence)
        md.add_render_rule("table_open", lambda *_: '<div class="table-wrap"><table>\n')
        md.add_render_rule("table_close", lambda *_: "</table></div>\n")
        return md

    def _parse(self, text: str, src: Path, out: Path, *, label: str | None = None) -> Rendered:
        """Parse + chuẩn bị token: id heading, link .md → .html (tương đối từ `out`), checkbox task list.
        `label` = tên nguồn để ghi link hỏng (None → không ghi, dùng khi parse lại cho trang khác)."""
        tokens = self.md.parse(text)
        r = Rendered(tokens)
        seen: dict[str, int] = {}
        texts: list[str] = []
        for i, tok in enumerate(tokens):
            if tok.type == "heading_open":
                inline = tokens[i + 1]
                plain = _plain(inline)
                slug = slugify(plain)
                n = seen.get(slug, 0)
                seen[slug] = n + 1
                hid = slug if n == 0 else f"{slug}-{n}"
                tok.attrSet("id", hid)
                level = int(tok.tag[1])
                if level == 1 and not r.title:
                    r.title = plain
                elif level in (2, 3):
                    r.headings.append((level, plain, hid))
                anchor = Token("html_inline", "", 0)
                anchor.content = f' <a class="anchor" href="#{esc(hid)}" aria-label="Liên kết tới mục này">#</a>'
                inline.children = [*(inline.children or []), anchor]
            elif tok.type == "list_item_open":
                _task(tok, tokens, i)
            elif tok.type == "fence" and tok.info.strip().split(" ")[0] == "archify":
                texts.extend(self._diagram(tok, src, out, label))
            elif tok.type == "inline":
                for child in tok.children or []:
                    if child.type == "link_open":
                        self._link(child, src, out, label)
                texts.append(_plain(tok))
        r.text = re.sub(r"\s+", " ", " ".join(texts)).strip()[:SEARCH_TEXT_CAP]
        return r

    def _diagram(self, tok: Token, src: Path, out: Path, label: str | None) -> list[str]:
        """Khối ```archify chứa đường dẫn spec (tương đối từ .md) → dữ liệu cho figure; trả chữ để đưa vào tìm kiếm."""
        path = tok.content.strip()
        spec = (src.parent / path).resolve()
        if not spec.is_file() or not diagram_kind(spec):
            if label:
                self._broken.add((label, path))
            tok.meta = {"missing": path}
            return []
        data = json.loads(spec.read_text(encoding="utf-8"))
        title = str((data.get("meta") or {}).get("title") or spec.stem)
        cards = [c for c in data.get("cards") or [] if isinstance(c, dict)]
        page = diagram_html(spec)
        tok.meta = {"href": _rel(page, out), "title": title, "ratio": self._ratio(page), "cards": cards}
        return [title] + [str(x) for c in cards for x in [c.get("title", ""), *(c.get("items") or [])]]

    def _ratio(self, page: Path) -> tuple[str, str]:
        if page not in self._ratios:
            m = VIEWBOX_RE.search(page.read_text(encoding="utf-8", errors="ignore")) if page.is_file() else None
            self._ratios[page] = (_num(m.group(1)), _num(m.group(2))) if m else ("16", "9")
        return self._ratios[page]

    def _render(self, tokens: list[Token]) -> str:
        return self.md.renderer.render(tokens, self.md.options, {})

    def _inline(self, tok: Token) -> str:
        return self.md.renderer.renderInline(tok.children or [], self.md.options, {})

    def _link(self, tok: Token, src: Path, out: Path, label: str | None) -> None:
        href = str(tok.attrGet("href") or "")
        if not href or href.startswith("#"):
            return
        if SCHEME_RE.match(href):
            tok.attrSet("target", "_blank")
            tok.attrSet("rel", "noopener")
            return
        path, _, frag = href.partition("#")
        target = (src.parent / path).resolve()
        if not target.exists():
            if label:
                self._broken.add((label, href))
            return
        new = self._target(target)
        if new is None:
            tok.attrSet("href", _rel(target, out) + (f"#{frag}" if frag else ""))
            tok.attrSet("class", "repo-link")
            tok.attrSet("title", "File trong repo (ngoài .claude) — mở được khi xem từ bản checkout")
            return
        tok.attrSet("href", _rel(new, out) + (f"#{frag}" if frag else ""))

    def _target(self, target: Path) -> Path | None:
        """File / thư mục đích → trang HTML tương ứng; None = nằm ngoài site (giữ link tới file repo)."""
        if target == self.root / "CLAUDE.md":
            return self.dir / "index.html"
        if not target.is_relative_to(self.dir):
            return None
        if target.is_file():
            return target.with_suffix(".html") if target.suffix == ".md" else target
        probe = target
        while probe.is_relative_to(self.dir):  # thư mục → CLAUDE.md gần nhất (vd `architecture/` → CLAUDE của domain)
            if (probe / "CLAUDE.md").is_file():
                return probe / "CLAUDE.html"
            if probe == self.dir:
                break
            probe = probe.parent
        return self.dir / "index.html"

    # ── dữ liệu ─────────────────────────────────────────────────────────────
    def _sources(self) -> list[Path]:
        return sorted(p for p in self.dir.rglob("*.md") if p.relative_to(self.dir).parts[0] not in (ASSETS, "skills"))

    def _menus(self, sources: list[Path]) -> dict[Path, MenuRow]:
        """Bảng menu trong `<domain>/CLAUDE.md`: | [file](…) | Trạng thái | Nội dung | → trạng thái + mô tả dự phòng."""
        rows: dict[Path, MenuRow] = {}
        index = self.dir / "index.html"
        for src in (p for p in sources if p.name == "CLAUDE.md"):
            r = self._parse(src.read_text(encoding="utf-8"), src, index)
            cells: list[Token] = []
            for tok in r.tokens:
                if tok.type == "tr_open":
                    cells = []
                elif tok.type == "inline" and tok.level >= 3:  # ô bảng
                    cells.append(tok)
                elif tok.type == "tr_close" and len(cells) >= 3:
                    first = next((c for c in cells[0].children or [] if c.type == "link_open"), None)
                    raw = str(first.attrGet("href") or "") if first else ""
                    if not raw.endswith(".html"):
                        continue
                    target = (self.dir / raw.partition("#")[0]).resolve().with_suffix(".md")
                    rows.setdefault(target, MenuRow(canon_status(_plain(cells[1])), self._inline(cells[2]), len(rows)))
        return rows

    def _doc(self, src: Path, menu: dict[Path, MenuRow]) -> Doc:
        text = src.read_text(encoding="utf-8")
        rel = PurePosixPath(src.relative_to(self.dir).as_posix())
        r = self._parse(text, src, src.with_suffix(".html"), label=rel.as_posix())
        row = menu.get(src.resolve())
        own = next(
            (
                canon_status(line)
                for line in text.splitlines()[:25]
                if "Trạng thái" in line and not line.lstrip().startswith("|") and canon_status(line)
            ),
            None,
        )
        dates = UPDATED_RE.findall(text)
        parts = rel.parts
        return Doc(
            src=src,
            rel=rel,
            url=rel.with_suffix(".html").as_posix(),
            domain=parts[0] if len(parts) > 1 else "",
            section=parts[1] if len(parts) > 2 else "",
            title=r.title.removeprefix("CLAUDE.md — ") or rel.stem,
            status=own or (row.status if row else None),
            summary=row.summary if row else "",
            updated=dates[-1] if dates else None,
            body=self._render(r.tokens),
            headings=r.headings,
            text=r.text,
            order=row.order if row else 10_000,
        )

    def _domains(self) -> list[Domain]:
        root_md = self.root / "CLAUDE.md"
        order = []
        if root_md.is_file():
            order = list(
                dict.fromkeys(re.findall(r"\.claude/([^/)\s]+)/CLAUDE\.md", root_md.read_text(encoding="utf-8")))
            )
        keys = sorted({d.domain for d in self.docs}, key=lambda k: (order.index(k) if k in order else len(order), k))
        out = []
        for key in keys:
            docs = [d for d in self.docs if d.domain == key]
            home = next((d for d in docs if d.rel.name == "CLAUDE.md" and len(d.rel.parts) == 2), None)
            rest = sorted(
                (d for d in docs if d is not home),
                key=lambda d: (
                    list(SECTIONS).index(d.section) if d.section in SECTIONS else len(SECTIONS),
                    d.section,
                    d.order,
                    d.rel.as_posix(),
                ),
            )
            intro = self._intro(home) if home else ""
            out.append(Domain(key, home.title if home else key, intro, home, rest))
        return out

    def _intro(self, home: Doc) -> str:
        r = self._parse(home.src.read_text(encoding="utf-8"), home.src, self.dir / "index.html")
        depth = 0
        for i, tok in enumerate(r.tokens):
            if tok.type == "blockquote_open":
                depth += 1
            elif tok.type == "blockquote_close":
                depth -= 1
            elif tok.type == "paragraph_open" and depth == 0 and tok.level == 0:
                return self._inline(r.tokens[i + 1])
        return ""

    def short(self, doc: Doc, domains: dict[str, Domain]) -> str:
        if doc.rel.name == "CLAUDE.md" and len(doc.rel.parts) == 2:
            return "Tổng quan"
        head, sep, tail = doc.title.partition(" — ")
        dom = domains.get(doc.domain)
        first = (dom.title.split()[0] if dom and dom.title else doc.domain).casefold()
        return tail if sep and head.casefold() in (first, doc.domain.casefold()) else doc.title
