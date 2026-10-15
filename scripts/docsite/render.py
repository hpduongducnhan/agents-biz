"""Dựng HTML trang doc từ dữ liệu đã đọc: khung trang, menu, trang tài liệu, index, chỉ mục tìm kiếm."""

# ruff: noqa: E501 — khuôn HTML giữ mỗi thẻ trên một dòng cho dễ đọc

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

from markdown_it.token import Token

from docsite.common import (
    ASSETS,
    MARK,
    RECENT_DECISIONS,
    SECTIONS,
    SITE,
    STATUS_CLASS,
    Doc,
    Domain,
    _highlight_css,
    _plain,
    _sections,
    badge,
    canon_status,
    esc,
)
from docsite.parse import SiteParser


class Site(SiteParser):
    """Trang review `.claude/`: đọc (SiteParser) + dựng HTML."""

    # ── trang ───────────────────────────────────────────────────────────────
    def build(self) -> dict[Path, str]:
        self._broken = set()
        sources = self._sources()
        menu = self._menus(sources)
        self.docs = [self._doc(p, menu) for p in sources]
        domains = self._domains()
        out = {d.out: self._page(d, domains) for d in self.docs}
        out[self.dir / "index.html"] = self._index(domains)
        out[self.dir / ASSETS / "search-index.js"] = self._search(domains)
        out[self.dir / ASSETS / "highlight.css"] = _highlight_css()
        self.broken = sorted(self._broken)
        return out

    def _nav(self, domains: list[Domain], here: str) -> str:
        base = posixpath.dirname(here)
        by_key = {d.key: d for d in domains}
        parts = []
        for dom in domains:
            items = []
            section = None
            for doc in ([dom.home] if dom.home else []) + dom.docs:
                if doc.section != section and doc is not dom.home:
                    section = doc.section
                    items.append(f'<li class="nav-sec">{esc(SECTIONS.get(section, section) or "Khác")}</li>')
                cur = ' class="active" aria-current="page"' if doc.url == here else ""
                dot = (
                    f'<i class="dot st-{STATUS_CLASS[doc.status]}" title="{esc(doc.status)}"></i>' if doc.status else ""
                )
                items.append(
                    f'<li><a href="{esc(posixpath.relpath(doc.url, base or "."))}"{cur} title="{esc(doc.title)}">'
                    f"<span>{esc(self.short(doc, by_key))}</span>{dot}</a></li>"
                )
            open_ = " open" if here.startswith(f"{dom.key}/") or here == "index.html" else ""
            parts.append(
                f'<details class="nav-group"{open_}><summary>{esc(dom.title)}</summary><ul>{"".join(items)}</ul></details>'
            )
        return "".join(parts)

    def _shell(self, *, title: str, here: str, domains: list[Domain], main: str, toc: str = "", body_class: str) -> str:
        up = "../" * here.count("/")
        home = ' class="active" aria-current="page"' if here == "index.html" else ""
        return f"""<!doctype html>
<html lang="vi" data-root="{up}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{MARK}
<title>{esc(title)}</title>
<link rel="icon" href="{up}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{up}assets/highlight.css">
<link rel="stylesheet" href="{up}assets/docs.css">
<script>(function(){{var t;try{{t=localStorage.getItem("bw-docs-theme")}}catch(e){{}}if(t!=="light"&&t!=="dark")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=t}})()</script>
<script src="{up}assets/docs.js" defer></script>
</head>
<body class="{body_class}">
<a class="skip" href="#main">Bỏ qua menu</a>
<header class="topbar">
<button class="icon-btn nav-toggle" type="button" aria-label="Menu tài liệu" aria-controls="sidebar" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>
<a class="brand" href="{up}index.html"><span class="brand-mark">M</span><span class="brand-name">{SITE}</span><span class="brand-sub">docs</span></a>
<div class="search" role="search">
<svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
<input type="search" id="search" placeholder="Tìm tài liệu…" autocomplete="off" spellcheck="false" aria-label="Tìm trong tài liệu" aria-controls="search-results" aria-expanded="false">
<kbd class="search-key">/</kbd>
<div class="search-results" id="search-results" role="listbox" hidden></div>
</div>
<button class="icon-btn theme-toggle" type="button" aria-label="Đổi giao diện sáng / tối"><svg class="i-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><svg class="i-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg></button>
</header>
<div class="layout">
<nav class="sidebar" id="sidebar" aria-label="Tài liệu">
<a class="nav-home" href="{up}index.html"{home}>Trang review</a>
{self._nav(domains, here)}
</nav>
<div class="scrim" hidden></div>
<main class="content" id="main">
{main}
</main>
{toc}
</div>
</body>
</html>
"""

    def _page(self, doc: Doc, domains: list[Domain]) -> str:
        up = "../" * doc.url.count("/")
        dom = next((d for d in domains if d.key == doc.domain), None)
        crumbs = [f'<a href="{up}index.html">Tổng quan</a>']
        if dom and dom.home and dom.home is not doc:
            crumbs.append(
                f'<a href="{esc(posixpath.relpath(dom.home.url, posixpath.dirname(doc.url)))}">{esc(dom.title)}</a>'
            )
        elif dom:
            crumbs.append(f"<span>{esc(dom.title)}</span>")
        if doc.section:
            crumbs.append(f"<span>{esc(SECTIONS.get(doc.section, doc.section))}</span>")
        meta = [badge(doc.status)]
        if doc.updated:
            meta.append(f'<span class="meta-date">Cập nhật {esc(doc.updated)}</span>')
        meta.append(f'<code class="meta-src">.claude/{esc(doc.rel.as_posix())}</code>')
        toc = ""
        if len(doc.headings) >= 2:
            links = "".join(
                f'<li class="lvl{lvl}"><a href="#{esc(hid)}">{esc(text)}</a></li>' for lvl, text, hid in doc.headings
            )
            toc = f'<aside class="toc" aria-label="Mục lục"><div class="toc-title">Trong trang này</div><ul>{links}</ul></aside>'
        main = f"""<nav class="crumbs" aria-label="Vị trí">{" <span class='sep'>/</span> ".join(crumbs)}</nav>
<div class="doc-meta">{"".join(meta)}</div>
<article class="prose">
{doc.body}</article>
<footer class="doc-foot">Sinh từ <code>.claude/{esc(doc.rel.as_posix())}</code> bằng <code>make docs</code> — sửa file .md rồi chạy lại.</footer>"""
        return self._shell(
            title=f"{doc.title} · {SITE}", here=doc.url, domains=domains, main=main, toc=toc, body_class="page-doc"
        )

    # ── index ───────────────────────────────────────────────────────────────
    def _index(self, domains: list[Domain]) -> str:
        index = self.dir / "index.html"
        root_md = self.root / "CLAUDE.md"
        overview, extra, name = "", [], SITE
        if root_md.is_file():
            r = self._parse(root_md.read_text(encoding="utf-8"), root_md, index, label="CLAUDE.md")
            name = (r.title.removeprefix("CLAUDE.md — ") or SITE).strip()
            for title, hid, tokens in _sections(r.tokens):
                html_ = self._render(tokens)
                if hid == "project-context":
                    overview = html_
                else:
                    extra.append(
                        f'<details class="root-sec" id="{esc(hid)}"><summary>{esc(title)}</summary>'
                        f'<div class="prose">{html_}</div></details>'
                    )
        counts: dict[str, int] = {}
        for d in self.docs:
            if d.status:
                counts[d.status] = counts.get(d.status, 0) + 1
        decisions = self._decisions()
        updated = max((d.updated for d in self.docs if d.updated), default="")
        stats = [f'<div class="stat"><b>{len(self.docs)}</b><span>tài liệu</span></div>']
        stats += [
            f'<div class="stat st-{STATUS_CLASS[s]}"><b>{counts[s]}</b><span>{esc(s)}</span></div>'
            for s in STATUS_CLASS
            if counts.get(s)
        ]
        if decisions:
            stats.append(f'<div class="stat"><b>{len(decisions)}</b><span>quyết định</span></div>')
        if updated:
            stats.append(f'<div class="stat"><b>{esc(updated)}</b><span>cập nhật gần nhất</span></div>')

        sections = [
            f"""<section class="hero">
<p class="eyebrow">Tài liệu thiết kế · review tính năng</p>
<h1>{esc(name)}</h1>
<p class="lede">Bản HTML của mọi file <code>.md</code> trong <code>.claude/</code> — đọc trên trình duyệt hoặc gửi cả thư mục cho team. Bấm <kbd>/</kbd> để tìm.</p>
<div class="stats">{"".join(stats)}</div>
</section>"""
        ]
        if overview:
            sections.append(
                f'<section class="block" id="tong-quan"><h2>Tổng quan dự án</h2><div class="prose">{overview}</div></section>'
            )
        features = self._features()
        if features:
            sections.append(
                f'<section class="block" id="tinh-nang"><h2>Tính năng · sub-project</h2>{features}</section>'
            )
        sections.append(self._domain_cards(domains))
        if decisions:
            url = self._decisions_home()
            items = "".join(
                f'<li><a href="{esc(u)}#{esc(hid)}">{esc(text)}</a></li>'
                for text, hid, u in reversed(decisions[-RECENT_DECISIONS:])
            )
            sections.append(
                f'<section class="block" id="quyet-dinh"><h2>Quyết định gần đây</h2><ol class="decisions">{items}</ol>'
                f'<p class="more"><a href="{esc(url)}">Toàn bộ {len(decisions)} quyết định →</a></p></section>'
            )
        if extra:
            sections.append(
                f'<section class="block" id="quy-tac"><h2>Quy tắc dự án (CLAUDE.md gốc)</h2>{"".join(extra)}</section>'
            )
        return self._shell(
            title=f"{name} · Review tài liệu",
            here="index.html",
            domains=domains,
            main="\n".join(sections),
            body_class="page-index",
        )

    def _find(self, name: str) -> Doc | None:
        hits = [d for d in self.docs if d.rel.name == name]
        return next((d for d in hits if d.section == "design"), hits[0] if hits else None)

    def _features(self) -> str:
        """Bảng sub-project đầu tiên trong roadmap.md → thẻ tính năng (link viết lại tương đối từ index)."""
        doc = self._find("roadmap.md")
        if not doc:
            return ""
        r = self._parse(doc.src.read_text(encoding="utf-8"), doc.src, self.dir / "index.html")
        rows: list[list[Token]] = []
        cells: list[Token] = []
        started = False
        for tok in r.tokens:
            if tok.type == "table_open":
                if started:
                    break
                started = True
            elif tok.type == "tbody_open":
                rows = []
            elif tok.type == "tr_open":
                cells = []
            elif tok.type == "inline" and started and tok.level >= 3:
                cells.append(tok)
            elif tok.type == "tr_close" and started and len(cells) >= 4:
                rows.append(cells)
            elif tok.type == "table_close":
                break
        cards = []
        for cells in rows:
            status = canon_status(_plain(cells[3]))
            cards.append(
                f'<article class="feature" data-status="{esc(status or "")}">'
                f'<div class="feature-head"><span class="feature-id">{esc(_plain(cells[0]))}</span>{badge(status)}</div>'
                f"<h3>{esc(_plain(cells[1]))}</h3><p>{self._inline(cells[2])}</p>"
                f'<div class="feature-status">{self._inline(cells[3])}</div></article>'
            )
        if not cards:
            return ""
        return f'<div class="features">{"".join(cards)}</div><p class="more"><a href="{esc(doc.url)}">Lộ trình đầy đủ →</a></p>'

    def _decisions(self) -> list[tuple[str, str, str]]:
        """Mục `### D<n>` của nhật ký quyết định — một file `decisions.md` hoặc package `decisions/` (R25)."""
        docs = [d for d in self.docs if d.rel.name == "decisions.md" or d.rel.parent.name == "decisions"]
        found = [
            (int(m.group(1)), text, hid, d.url)
            for d in docs
            for lvl, text, hid in d.headings
            if lvl == 3 and (m := re.match(r"D(\d+)\b", text))
        ]
        return [(text, hid, url) for _, text, hid, url in sorted(found)]

    def _decisions_home(self) -> str:
        home = next((d for d in self.docs if d.rel.parent.name == "decisions" and d.rel.name == "README.md"), None)
        return home.url if home else self._decisions()[0][2]

    def _domain_cards(self, domains: list[Domain]) -> str:
        chips = "".join(
            f'<button type="button" class="chip" data-filter="{esc(s)}">{esc(s)}</button>'
            for s in STATUS_CLASS
            if any(d.status == s for d in self.docs)
        )
        cards = []
        for dom in domains:
            items = []
            section = None
            for doc in dom.docs:
                if doc.section != section:
                    section = doc.section
                    items.append(f'<li class="doc-sec">{esc(SECTIONS.get(section, section) or "Khác")}</li>')
                summary = f'<span class="doc-sum">{doc.summary}</span>' if doc.summary else ""
                items.append(
                    f'<li class="doc" data-status="{esc(doc.status or "")}"><a href="{esc(doc.url)}">{esc(doc.title)}</a>'
                    f"{badge(doc.status)}{summary}</li>"
                )
            head = f'<a href="{esc(dom.home.url)}">{esc(dom.title)}</a>' if dom.home else esc(dom.title)
            intro = f'<p class="domain-intro">{dom.intro}</p>' if dom.intro else ""
            cards.append(
                f'<article class="domain" id="d-{esc(dom.key)}"><h3>{head}</h3>{intro}'
                f'<ul class="doc-list">{"".join(items)}</ul></article>'
            )
        return (
            '<section class="block" id="tai-lieu"><h2>Tài liệu theo domain</h2>'
            f'<div class="chips" role="group" aria-label="Lọc theo trạng thái">'
            f'<button type="button" class="chip active" data-filter="">Tất cả</button>{chips}</div>'
            f'<div class="domains">{"".join(cards)}</div></section>'
        )

    def _search(self, domains: list[Domain]) -> str:
        titles = {d.key: d.title for d in domains}
        data = [
            {
                "t": d.title,
                "u": d.url,
                "d": titles.get(d.domain, d.domain),
                "s": d.status or "",
                "h": [[text, hid] for _, text, hid in d.headings],
                "x": d.text,
            }
            for d in self.docs
        ]
        return "window.DOCS_SEARCH=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
