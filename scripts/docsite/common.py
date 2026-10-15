"""Hằng số, model dữ liệu và helper markdown dùng chung của trang doc."""

# ruff: noqa: E501 — khuôn HTML giữ mỗi thẻ trên một dòng cho dễ đọc

from __future__ import annotations

import html
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from markdown_it.token import Token
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.util import ClassNotFound

REPO = Path(__file__).resolve().parents[2]
DOCS = ".claude"
ASSETS = "assets"
MARK = '<meta name="generator" content="bw-docs">'
SITE = "BizWithAgents"

STATUSES = {"đã chốt": "ĐÃ CHỐT", "xong": "Xong", "đề xuất": "ĐỀ XUẤT", "tầm nhìn": "TẦM NHÌN", "đang làm": "Đang làm"}
STATUSES["chưa bắt đầu"] = "Chưa bắt đầu"
STATUS_CLASS = {
    "ĐÃ CHỐT": "locked",
    "Xong": "done",
    "ĐỀ XUẤT": "proposed",
    "TẦM NHÌN": "vision",
    "Đang làm": "wip",
    "Chưa bắt đầu": "todo",
}
STATUS_RE = re.compile("|".join(re.escape(s) for s in STATUSES), re.IGNORECASE)
UPDATED_RE = re.compile(r"\*Cập nhật: (\d{4}-\d{2}-\d{2})")
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
SECTIONS = {"architecture": "Kiến trúc", "design": "Thiết kế", "plans": "Plan"}
RECENT_DECISIONS = 8
SEARCH_TEXT_CAP = 40_000
DIAGRAMS = "diagrams"  # <domain>/diagrams/<tên>.<loại>.json = spec archify; <tên>.html = bản archify sinh
DIAGRAM_TYPES = ("architecture", "workflow", "sequence", "dataflow", "lifecycle")
LOCK = "diagrams.lock.json"
ARCHIFY = Path.home() / ".claude/skills/archify/bin/archify.mjs"
VIEWBOX_RE = re.compile(r'<svg\b[^>]*\bviewBox="0 0 ([\d.]+) ([\d.]+)"')
MERMAID_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*mermaid\b", re.MULTILINE)


def slugify(text: str) -> str:
    """Anchor kiểu GitHub: chữ thường, bỏ ký tự không phải chữ / số / `-` / `_` / khoảng trắng, khoảng trắng → `-`."""
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def canon_status(text: str) -> str | None:
    m = STATUS_RE.search(text)
    return STATUSES[m.group(0).casefold()] if m else None


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def badge(status: str | None) -> str:
    if not status:
        return ""
    return f'<span class="badge st-{STATUS_CLASS[status]}">{esc(status)}</span>'


def _plain(inline: Token) -> str:
    parts = []
    for c in inline.children or []:
        if c.type in ("text", "code_inline"):
            parts.append(c.content)
        elif c.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts)


@dataclass
class Rendered:
    tokens: list[Token]
    title: str = ""
    headings: list[tuple[int, str, str]] = field(default_factory=list)
    text: str = ""


@dataclass
class MenuRow:
    status: str | None
    summary: str
    order: int


@dataclass
class Doc:
    src: Path
    rel: PurePosixPath
    url: str
    domain: str
    section: str
    title: str
    status: str | None
    summary: str
    updated: str | None
    body: str
    headings: list[tuple[int, str, str]]
    text: str
    order: int

    @property
    def out(self) -> Path:
        return self.src.with_suffix(".html")


@dataclass
class Domain:
    key: str
    title: str
    intro: str
    home: Doc | None
    docs: list[Doc]


# ── helpers ─────────────────────────────────────────────────────────────────
def _rel(target: Path, out: Path) -> str:
    return posixpath.relpath(target.as_posix(), out.parent.as_posix())


def _task(item: Token, tokens: list[Token], i: int) -> None:
    """`- [ ] việc` / `- [x] việc` → checkbox (chỉ đọc)."""
    inline = next((t for t in tokens[i + 1 : i + 3] if t.type == "inline"), None)
    first = (inline.children or [None])[0] if inline else None
    if first is None or first.type != "text" or first.content[:3] not in ("[ ]", "[x]", "[X]"):
        return
    if len(first.content) > 3 and first.content[3] != " ":
        return
    checked = first.content[1] != " "
    first.content = first.content[4:]
    box = Token("html_inline", "", 0)
    box.content = f'<input type="checkbox" disabled{" checked" if checked else ""}> '
    inline.children = [box, *inline.children]
    item.attrSet("class", "task")


def _fence(self, tokens: list[Token], idx: int, options, env) -> str:  # noqa: ANN001 — chữ ký render rule của markdown-it
    tok = tokens[idx]
    lang = tok.info.strip().split(" ")[0] if tok.info else ""
    if lang == "archify":
        return _figure(tok.meta)
    try:
        lexer = get_lexer_by_name(lang) if lang else TextLexer()
    except ClassNotFound:
        lexer = TextLexer()
    body = highlight(tok.content, lexer, HtmlFormatter(cssclass="hl"))
    label = f'<span class="code-lang">{esc(lang)}</span>' if lang else '<span class="code-lang"></span>'
    return f'<div class="code">{label}{body}</div>\n'


def _figure(meta: dict) -> str:
    if "missing" in meta:
        return f'<div class="diagram-missing">Thiếu spec sơ đồ: <code>{esc(meta["missing"])}</code></div>\n'
    href, title = esc(meta["href"]), esc(meta["title"])
    w, h = (esc(v) for v in meta["ratio"])  # + 1rem = đệm quanh SVG ở chế độ embed của archify
    cards = "".join(
        f'<div class="diagram-card dot-{esc(str(c.get("dot", "slate")))}"><b>{esc(str(c.get("title", "")))}</b>'
        f"<ul>{''.join(f'<li>{esc(str(i))}</li>' for i in c.get('items') or [])}</ul></div>"
        for c in meta["cards"]
    )
    return (
        f'<figure class="diagram">\n<div class="diagram-box"><iframe class="diagram-frame" src="{href}?embed=1" title="{title}" '
        f'loading="lazy" style="aspect-ratio: {w} / {h}; height: calc(100cqw * {h} / {w} + 1rem)"></iframe></div>\n'
        f'<figcaption><span class="diagram-title">{title}</span>'
        f'<a class="diagram-open" href="{href}" target="_blank" rel="noopener">Mở toàn màn hình ↗</a></figcaption>\n'
        + (f'<div class="diagram-cards">{cards}</div>\n' if cards else "")
        + "</figure>\n"
    )


def _num(value: str) -> str:
    n = float(value)
    return str(int(n)) if n.is_integer() else str(n)


def _sections(tokens: list[Token]) -> list[tuple[str, str, list[Token]]]:
    """Tách theo H2: [(tiêu đề, id, token của phần thân)] — bỏ phần trước H2 đầu (tiêu đề + menu)."""
    out: list[tuple[str, str, list[Token]]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open" and tok.tag == "h2":
            title = _plain(tokens[i + 1])
            hid = str(tok.attrGet("id") or slugify(title))
            j = i + 3
            while j < len(tokens) and not (tokens[j].type == "heading_open" and tokens[j].tag == "h2"):
                j += 1
            body = [t for t in tokens[i + 3 : j] if t.type != "hr"]
            out.append((title, hid, body))
            i = j
        else:
            i += 1
    return out


def _highlight_css() -> str:
    light = HtmlFormatter(style="default").get_style_defs(".hl")
    dark = HtmlFormatter(style="github-dark").get_style_defs(':root[data-theme="dark"] .hl')
    return f"/* sinh bởi scripts/docs_site.py (Pygments) — không sửa tay */\n{light}\n{dark}\n"
