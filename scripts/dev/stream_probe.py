"""Đo nhịp stream của provider đang gắn cho một agent (D23): chữ về từng phần hay dồn cục — chỉ đọc cấu hình,
không ghi DB, không in key.

    cd backend && poetry run python ../scripts/dev/stream_probe.py [--agent general] [--prompt "…"] [--raw]

In một dòng JSON mỗi cách đo:
- `langchain`: đúng đường app dùng (`build_chat_model` + `astream`) — mốc từng chunk có chữ;
- `raw` (chỉ provider kiểu OpenAI, cờ `--raw`): gọi thẳng `/chat/completions` bằng httpx, mốc từng dòng SSE `data:`.
Số liệu: `ttft_ms`, `total_ms`, `chunks`, `chars`, `gen_ms` (chữ đầu → chữ cuối), `chars_per_s`, `max_gap_ms`,
`big_chunks` (chunk ≥ 80 ký tự) — gateway dồn cục thì `chunks` ít, `big_chunks` nhiều, `chars_per_s` rất cao.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx

from app.agent.config.registry import by_slug
from app.agent.runtime import keys
from app.agent.runtime.llm import PROVIDERS, build_chat_model
from app.core.connections.registry import close_connections, get_connections, init_connections
from app.core.settings import get_settings, use_settings

PROMPT = "Liệt kê 10 mẹo tiết kiệm tiền cho sinh viên, mỗi mẹo một câu đầy đủ."


def summary(kind: str, start: float, marks: list[tuple[float, int]]) -> dict:
    if not marks:
        return {"kind": kind, "chunks": 0}
    first, last = marks[0][0], marks[-1][0]
    gaps = [b[0] - a[0] for a, b in zip(marks, marks[1:], strict=False)]
    chars = sum(n for _, n in marks)
    gen = last - first
    return {
        "kind": kind,
        "ttft_ms": round((first - start) * 1000),
        "total_ms": round((last - start) * 1000),
        "chunks": len(marks),
        "chars": chars,
        "gen_ms": round(gen * 1000),
        "chars_per_s": round(chars / gen) if gen > 0 else None,
        "max_gap_ms": round(max(gaps) * 1000) if gaps else 0,
        "big_chunks": sum(1 for _, n in marks if n >= 80),
    }


async def via_langchain(spec, secret: str, prompt: str) -> dict:
    model = build_chat_model(spec, api_key=secret)
    marks: list[tuple[float, int]] = []
    start = time.monotonic()
    async for chunk in model.astream(prompt):
        text = chunk.text if isinstance(chunk.text, str) else ""
        if text:
            marks.append((time.monotonic(), len(text)))
    return summary("langchain", start, marks)


async def via_raw(spec, secret: str, prompt: str) -> dict:
    base = (spec.provider.base_url or "https://api.openai.com/v1").rstrip("/")
    body = {"model": spec.model.model_id, "stream": True, "messages": [{"role": "user", "content": prompt}]}
    headers = {"Authorization": f"Bearer {secret}", **(spec.provider.extra_headers or {})}
    marks: list[tuple[float, int]] = []
    start = time.monotonic()
    async with (
        httpx.AsyncClient(timeout=120) as client,
        client.stream("POST", f"{base}/chat/completions", json=body, headers=headers) as resp,
    ):
        if resp.status_code >= 400:
            return {"kind": "raw", "http_status": resp.status_code}
        async for line in resp.aiter_lines():
            if not line.startswith("data:") or line.strip() == "data: [DONE]":
                continue
            try:
                delta = json.loads(line[5:])["choices"][0]["delta"].get("content") or ""
            except (ValueError, KeyError, IndexError):
                continue
            if delta:
                marks.append((time.monotonic(), len(delta)))
    return summary("raw", start, marks)


async def main(opts: argparse.Namespace) -> int:
    s = get_settings()
    use_settings(s)
    await init_connections("work", s)
    try:
        conns = get_connections()
        async with conns.postgres.ro() as session:
            spec = await by_slug(session, conns.redis, opts.agent)
        if spec is None or spec.provider is None or spec.model is None:
            print(json.dumps({"error": f"agent {opts.agent} chưa gắn provider / model"}))
            return 1
        async with conns.postgres.rw() as session:
            picked = await keys.pick(session, conns.redis, s, spec)
        meta = {"agent": opts.agent, "provider_kind": spec.provider.kind, "model": spec.model.model_id}
        print(json.dumps({**meta, **await via_langchain(spec, picked.secret, opts.prompt)}, ensure_ascii=False))
        if opts.raw and PROVIDERS[spec.provider.kind] == "openai":
            print(json.dumps({**meta, **await via_raw(spec, picked.secret, opts.prompt)}, ensure_ascii=False))
        return 0
    finally:
        await close_connections()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--agent", default="general", help="slug agent (mặc định general)")
    p.add_argument("--prompt", default=PROMPT)
    p.add_argument("--raw", action="store_true", help="đo thêm bằng httpx thẳng tới /chat/completions")
    sys.exit(asyncio.run(main(p.parse_args())))
