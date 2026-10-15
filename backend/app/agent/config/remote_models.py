"""Danh sách model phía provider (Studio — chọn model thay vì gõ tay): gọi `GET …/models` theo loại provider, đi hết
các trang, chuẩn hoá về `RemoteModel` (id dùng khi gọi LLM, tên hiển thị, context, model chat?, giá nếu provider có —
kiểu OpenRouter). Key đi trong header (Gemini: `x-goog-api-key`), không nằm trên URL."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx2

MAX_PAGES = 10
TIMEOUT = 15
PER_MILLION = Decimal(1_000_000)
NOT_CHAT = ("embed", "whisper", "tts", "dall-e", "moderation", "transcribe", "image", "audio", "rerank")
DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "google_genai": "https://generativelanguage.googleapis.com/v1beta",
}


class RemoteError(Exception):
    """Provider trả lỗi / không gọi được — `status` = mã HTTP (0 = lỗi mạng)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class RemoteModel:
    model_id: str
    name: str
    description: str
    context_window: int | None
    chat: bool
    input_price_per_1m: Decimal | None = None
    output_price_per_1m: Decimal | None = None
    cache_read_price_per_1m: Decimal | None = None


def base_url(kind: str, configured: str | None) -> str:
    return (configured or DEFAULT_BASE.get(kind, "")).rstrip("/")


def _headers(kind: str, key: str) -> dict[str, str]:
    if kind == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if kind == "google_genai":
        return {"x-goog-api-key": key}
    return {"authorization": f"Bearer {key}"}


def _int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _per_million(value: Any) -> Decimal | None:
    """Giá mỗi token (chuỗi kiểu OpenRouter) → giá mỗi 1M token; âm / lạ → None."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return (d * PER_MILLION).quantize(Decimal("0.0001")) if d >= 0 else None


def _google(item: dict) -> RemoteModel:
    raw = str(item.get("name") or "")
    model_id = raw.removeprefix("models/")
    methods = item.get("supportedGenerationMethods") or []
    return RemoteModel(
        model_id=model_id,
        name=str(item.get("displayName") or model_id),
        description=str(item.get("description") or "")[:300],
        context_window=_int(item.get("inputTokenLimit")),
        chat="generateContent" in methods,
    )


def _anthropic(item: dict) -> RemoteModel:
    model_id = str(item.get("id") or "")
    return RemoteModel(
        model_id=model_id,
        name=str(item.get("display_name") or model_id),
        description="",
        context_window=_int(item.get("max_input_tokens")),
        chat=True,
    )


def _openai(item: dict) -> RemoteModel:
    model_id = str(item.get("id") or "")
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    return RemoteModel(
        model_id=model_id,
        name=str(item.get("name") or model_id),
        description=str(item.get("description") or "")[:300],
        context_window=_int(item.get("context_length") or item.get("context_window")),
        chat=not any(t in model_id.lower() for t in NOT_CHAT),
        input_price_per_1m=_per_million(pricing["prompt"]) if "prompt" in pricing else None,
        output_price_per_1m=_per_million(pricing["completion"]) if "completion" in pricing else None,
        cache_read_price_per_1m=_per_million(pricing["input_cache_read"]) if "input_cache_read" in pricing else None,
    )


def _next(kind: str, body: dict) -> dict[str, str] | None:
    """Tham số trang sau; None = hết trang."""
    if kind == "google_genai" and body.get("nextPageToken"):
        return {"pageToken": str(body["nextPageToken"])}
    if kind == "anthropic" and body.get("has_more") and body.get("last_id"):
        return {"after_id": str(body["last_id"])}
    return None


async def fetch(kind: str, base: str, key: str, extra_headers: dict | None = None) -> tuple[list[RemoteModel], int]:
    """(model đã chuẩn hoá — model chat trước, rồi theo tên; thời gian gọi ms). Lỗi → `RemoteError`."""
    headers = {**_headers(kind, key), **(extra_headers or {})}
    params: dict[str, str] = {"pageSize": "1000"} if kind == "google_genai" else {}
    if kind == "anthropic":
        params = {"limit": "1000"}
    parse = {"google_genai": _google, "anthropic": _anthropic}.get(kind, _openai)
    out: dict[str, RemoteModel] = {}
    started = time.perf_counter()
    try:
        async with httpx2.AsyncClient(timeout=TIMEOUT) as client:
            for _ in range(MAX_PAGES):
                r = await client.get(f"{base}/models", headers=headers, params=params)
                if r.status_code >= 400:
                    raise RemoteError(r.status_code, r.text[:300].replace(key, "***"))
                body = r.json()
                items = body.get("data") or body.get("models") or []
                for item in items:
                    if isinstance(item, dict) and (m := parse(item)).model_id:
                        out.setdefault(m.model_id, m)
                nxt = _next(kind, body)
                if nxt is None:
                    break
                params = {**params, **nxt}
    except RemoteError:
        raise
    except Exception as exc:  # noqa: BLE001 — mạng / JSON hỏng → lỗi đọc được cho Studio
        raise RemoteError(0, f"{type(exc).__name__}: {str(exc)[:300]}".replace(key, "***")) from exc
    ms = int((time.perf_counter() - started) * 1000)
    return sorted(out.values(), key=lambda m: (not m.chat, m.name.lower())), ms
