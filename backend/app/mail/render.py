"""Mẫu thư Jinja2 theo ngôn ngữ: `templates/<tên>.<locale>.txt` (dòng đầu `Subject: …`, dòng trống, thân chữ) và
tuỳ chọn `templates/<tên>.<locale>.html` (thân HTML, autoescape). Thiếu bản theo locale → dùng `vi`; thiếu cả hai →
8001."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound, select_autoescape

from app.core.errors import AppException

TEMPLATES = Path(__file__).resolve().parent / "templates"
LOCALES = ("vi", "en")
DEFAULT_LOCALE = "vi"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    undefined=StrictUndefined,
    keep_trailing_newline=False,
)


def _locale(locale: str | None) -> str:
    return locale if locale in LOCALES else DEFAULT_LOCALE


def _get(template: str, locale: str, ext: str):
    for loc in dict.fromkeys((locale, DEFAULT_LOCALE)):
        try:
            return _env.get_template(f"{template}.{loc}.{ext}")
        except TemplateNotFound:
            continue
    return None


def render(template: str, locale: str | None, **ctx: Any) -> tuple[str, str, str | None]:
    """→ (subject, text, html | None)."""
    loc = _locale(locale)
    txt = _get(template, loc, "txt")
    if txt is None:
        raise AppException(8001, status_code=500, detail=f"Không có mẫu thư '{template}'")
    head, _, body = txt.render(**ctx).partition("\n\n")
    subject = head.removeprefix("Subject:").strip()
    html_tpl = _get(template, loc, "html")
    return subject, body.strip() + "\n", html_tpl.render(**ctx) if html_tpl is not None else None
