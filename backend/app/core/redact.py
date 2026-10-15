"""Che dữ liệu nhạy cảm trước khi ghi log (text, JSON, header, URL, DSN, body)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"
DEFAULT_REDACT_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "secret",
        "client_secret",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "private_key",
        "service_account_json",
    }
)
SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "api-key", "x-goog-api-key"}
)
_TEXT_TYPES = ("application/json", "application/x-www-form-urlencoded", "application/xml")
_PATTERN = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|sk-[A-Za-z0-9_-]{16,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|(?:api[-_]?key|password|token)=[^\s&\"']+)",
    re.IGNORECASE,
)
_DSN_PASSWORD = re.compile(r"(://[^:/@\s]*):[^@\s/]*@")  # user có thể rỗng (redis://:pw@host)


def build_keys(extra: Iterable[str]) -> frozenset[str]:
    return DEFAULT_REDACT_KEYS | frozenset(k.lower() for k in extra)


def redact_text(text: str) -> str:
    return _PATTERN.sub(REDACTED, _DSN_PASSWORD.sub(r"\1:***@", text))


_SEGMENT = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
_JSON_STR_FIELD = re.compile(r'("([^"\\]{1,100})"\s*:\s*)"(?:[^"\\]|\\.)*"')


def is_sensitive_key(key: str, keys: frozenset[str]) -> bool:
    """Khớp nguyên khoá (`password`) HOẶC một đoạn của khoá ghép (`new_password`, `clientSecret`, `x-api-key`)
    — `max_tokens` không bị che vì đoạn `tokens` không nằm trong danh sách."""
    low = key.lower()
    if low in keys or low.replace("-", "_") in keys:
        return True
    parts = [m.group().lower() for m in _SEGMENT.finditer(key)]
    joined = {"_".join(parts[i:j]) for i in range(len(parts)) for j in range(i + 1, min(len(parts), i + 2) + 1)}
    return any(part in keys for part in joined) or "".join(parts) in keys


def _redact_json_keys(text: str, keys: frozenset[str]) -> str:
    if not keys:
        return text

    def sub(m: re.Match) -> str:
        return f'{m.group(1)}"{REDACTED}"' if is_sensitive_key(m.group(2), keys) else m.group(0)

    return _JSON_STR_FIELD.sub(sub, text)


def redact_mapping(value, keys: frozenset[str]):
    if isinstance(value, Mapping):
        return {k: (REDACTED if is_sensitive_key(str(k), keys) else redact_mapping(v, keys)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_mapping(v, keys) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers:
        name = key.lower()
        out[name] = REDACTED if name in SENSITIVE_HEADERS else value
    return out


def _redact_pairs(pairs: list[tuple[str, str]], keys: frozenset[str]) -> str:
    return urlencode([(k, REDACTED if is_sensitive_key(k, keys) else v) for k, v in pairs], safe="[]")


def redact_url(url: str, keys: frozenset[str]) -> str:
    """Che query theo khoá bí mật + tham số `key` (API key trên URL, vd Gemini) — chỉ ở URL, không thêm `key` vào
    danh sách khoá chung (sẽ che nhầm `sort_key`, `primary_key`)."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode(
        [(k, REDACTED if k.lower() == "key" or is_sensitive_key(k, keys) else v) for k, v in pairs], safe="[]"
    )
    return urlunsplit(parts._replace(query=query))


def redact_dsn(url: str) -> str:
    return _DSN_PASSWORD.sub(r"\1:***@", url)


def _media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def is_text_content(content_type: str | None) -> bool:
    ct = _media_type(content_type)
    if ct == "text/event-stream":
        return False
    return ct.startswith("text/") or ct in _TEXT_TYPES or ct.endswith("+json")


def render_body(
    raw: bytes,
    content_type: str | None,
    keys: frozenset[str],
    max_bytes: int,
    total_size: int | None = None,
) -> str:
    """Body → chuỗi an toàn để log: chỉ nội dung dạng chữ, đã che, cắt theo `max_bytes`."""
    size = total_size if total_size is not None else len(raw)
    if not is_text_content(content_type):
        return f"<binary {size} bytes>"
    ct = _media_type(content_type)
    if size <= max_bytes and (ct == "application/json" or ct.endswith("+json")):
        try:
            return json.dumps(redact_mapping(json.loads(raw), keys), ensure_ascii=False)
        except ValueError:
            pass  # không phải JSON hợp lệ → che dạng text bên dưới
    if size <= max_bytes and ct == "application/x-www-form-urlencoded":
        return _redact_pairs(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True), keys)
    text = _redact_json_keys(redact_text(raw[:max_bytes].decode("utf-8", "replace")), keys)
    return text if size <= max_bytes else f"{text}…[truncated {size - max_bytes} bytes]"
