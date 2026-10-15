"""Gắn provider + model + credential vào mọi agent mặc định — chỉ DB dùng thử.

    cd backend && poetry run python ../scripts/seed_agent.py --provider openai_compatible \\
        --base-url http://127.0.0.1:8799/v1 --model fake-model --key fake-key          # LLM giả của stack thử
    cd backend && poetry run python ../scripts/seed_agent.py --provider anthropic --model claude-sonnet-5 \\
        --key-file k.txt

Chạy lại: cập nhật provider / model / credential cùng tên, không nhân đôi. In một dòng JSON; thoát 0 = đúng.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import select

from app.agent.config.models import Agent, AgentKey, AgentModel, AgentProvider
from app.auth.seed import seed_target_problem
from app.core.connections.postgres import Postgres
from app.core.settings import get_settings
from app.credentials.models import Credential
from app.credentials.service import seal

KINDS = ("openai", "anthropic", "google_genai", "openai_compatible")


def parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--provider", choices=KINDS, required=True)
    p.add_argument("--name", default="", help="tên provider (mặc định = loại)")
    p.add_argument("--base-url", default=None)
    p.add_argument("--model", required=True, help="tên model phía provider")
    p.add_argument("--model-name", default="")
    p.add_argument("--key", default=None, help="giá trị key (chỉ cho LLM giả / dev)")
    p.add_argument("--key-file", default=None)
    p.add_argument("--input-price", type=Decimal, default=Decimal(0))
    p.add_argument("--output-price", type=Decimal, default=Decimal(0))
    opts = p.parse_args(argv)
    if not (opts.key or opts.key_file):
        p.error("cần --key hoặc --key-file")
    return opts


async def run(opts: argparse.Namespace) -> dict:
    settings = get_settings()
    problem = seed_target_problem(settings)
    if problem:
        raise SystemExit(f"✗ từ chối: {problem}")
    secret = opts.key or Path(opts.key_file).read_text(encoding="utf-8").strip()
    name = opts.name or opts.provider
    pg = Postgres(settings)
    try:
        async with pg.rw() as s:
            provider = (await s.exec(select(AgentProvider).where(AgentProvider.name == name))).first()
            provider = provider or AgentProvider(name=name, kind=opts.provider)
            provider.kind, provider.base_url, provider.status = opts.provider, opts.base_url, "active"
            s.add(provider)
            await s.flush()
            model = (
                await s.exec(
                    select(AgentModel).where(AgentModel.provider_id == provider.id, AgentModel.model_id == opts.model)
                )
            ).first() or AgentModel(provider_id=provider.id, model_id=opts.model, name=opts.model_name or opts.model)
            model.input_price_per_1m, model.output_price_per_1m = opts.input_price, opts.output_price
            s.add(model)
            await s.flush()
            cred_name = f"{name} — seed"
            cred = (await s.exec(select(Credential).where(Credential.name == cred_name))).first()
            cred = cred or Credential(name=cred_name, secret_ciphertext="", key_id="", masked_hint="")
            cred.provider_id, cred.status = provider.id, "active"
            seal(cred, secret, settings)
            s.add(cred)
            await s.flush()
            agents = (await s.exec(select(Agent))).all()
            for a in agents:
                a.model_id = model.id
                s.add(a)
                await s.exec(delete(AgentKey).where(AgentKey.agent_id == a.id))
                s.add(AgentKey(agent_id=a.id, credential_id=cred.id, enabled=True))
            await s.flush()
            return {"provider": name, "model": opts.model, "credential": cred.masked_hint, "agents": len(agents)}
    finally:
        await pg.close()


def main() -> int:
    print(json.dumps(asyncio.run(run(parse(sys.argv[1:]))), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
