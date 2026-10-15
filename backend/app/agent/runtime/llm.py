"""Dựng chat model LangChain từ cấu hình đã đọc (`AgentSpec`) — mỗi lượt một model, key giải mã ngay trước khi dựng.
`max_retries=0`: mọi lần thử lại do lớp xoay key điều khiển."""

from __future__ import annotations

import importlib
import time

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.agent.config.registry import AgentSpec
from app.core.logging import get_logger

logger = get_logger(__name__)

PROVIDERS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google_genai": "google_genai",
    "openai_compatible": "openai",
}
# gói tích hợp `init_chat_model` chỉ import ở lần dựng model đầu tiên (openai ~0,4 s · anthropic ~1 s)
PROVIDER_PACKAGES = ("langchain_openai", "langchain_anthropic", "langchain_google_genai")


def warm_providers() -> list[str]:
    """Nạp sẵn gói tích hợp provider để lượt chat đầu sau khi worker khởi động không chậm thêm; trả gói đã nạp."""
    started = time.perf_counter()
    for name in PROVIDER_PACKAGES:
        importlib.import_module(name)
    logger.info(
        "nạp sẵn provider LLM %s trong %.2fs", ", ".join(PROVIDER_PACKAGES), time.perf_counter() - started,
        extra={"loc": "agt1001"},
    )  # fmt: skip
    return list(PROVIDER_PACKAGES)


def build_chat_model(spec: AgentSpec, *, api_key: str, stream: bool = True) -> BaseChatModel:
    """`stream=False` (cài đặt `chat_stream` tắt): gọi provider một lần; `disable_streaming` để LangGraph không
    ép stream khi có callback."""
    provider, model = spec.provider, spec.model
    kind = PROVIDERS[provider.kind]
    params = {**(provider.default_params or {}), **(spec.agent.params_override or {})}
    kwargs: dict = {"api_key": api_key, "max_retries": 0, **params}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    headers = provider.extra_headers or {}
    if kind == "openai":
        kwargs.update(streaming=True, stream_usage=True) if stream else kwargs.update(streaming=False)
        if headers:
            kwargs["default_headers"] = headers
    elif kind == "anthropic":
        kwargs["streaming"] = stream
        if headers:
            kwargs["default_headers"] = headers
    elif headers:
        kwargs["additional_headers"] = headers
    if not stream:
        kwargs["disable_streaming"] = True
    return init_chat_model(model.model_id, model_provider=kind, **kwargs)


def provider_kind(spec: AgentSpec) -> str:
    return spec.provider.kind if spec.provider is not None else ""
