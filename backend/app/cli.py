"""Launcher `bw` — mỗi lệnh là một process role: api · consume · work · schedule · migrate (+ keys trước migrate)."""

from __future__ import annotations

import asyncio
import json
import signal
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import typer
import uvicorn

from app.agent.debug import dump_session
from app.agent.eval import PASS_RATE, report, run_eval
from app.agent.runtime.llm import warm_providers
from app.agent.tasks import AGENT_LANE
from app.auth.keys import ensure_keypair, env_lines, generate_pem_pair
from app.auth.seed import SUPERADMIN_SEED_EMAIL, seed_target_problem, seed_test_users
from app.core.connections.postgres import Postgres
from app.core.connections.registry import Connections, close_connections, init_connections
from app.core.http_rules import HttpLogRules
from app.core.httpx_log import install_httpx_logging
from app.core.logging import configure_logging, get_logger
from app.core.messaging.lanes import parse_lanes
from app.core.messaging.runtime import run_consume, run_schedule, run_work, start_messaging, stop_messaging
from app.core.migrate import make_revision, run_migrations, run_post_migrate
from app.core.operations.runner import check_operations
from app.core.redact import build_keys
from app.core.settings import Settings, get_settings, use_settings
from app.credentials.crypto import new_key as new_fernet_key
from app.credentials.service import rotate_all
from app.domains import load_domains
from app.main import OPENAPI_FILE, render_openapi
from app.observability import close_observability, init_observability

logger = get_logger(__name__)

cli = typer.Typer(no_args_is_help=True, add_completion=False, help="BizWithAgents — launcher các process backend")


@cli.callback()
def _root() -> None:
    """BizWithAgents — launcher các process backend."""


@cli.command()
def api(
    host: str | None = typer.Option(None, help="Mặc định: HOST trong .env"),
    port: int | None = typer.Option(None, help="Mặc định: PORT trong .env"),
    reload: bool = typer.Option(False, help="Dev: tự nạp lại khi sửa code"),
) -> None:
    """Chạy process HTTP API."""
    s = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=host or s.HOST,
        port=port or s.PORT,
        workers=1 if reload else s.WORKERS,
        reload=reload,
        log_config=None,
        access_log=False,
    )


@cli.command()
def keys(
    print_env: bool = typer.Option(
        False, "--print", help="In cặp khoá mới thành 2 dòng env (dán vào Coolify), không ghi file"
    ),
) -> None:
    """Khoá ký JWT: PEM trong env thì thôi; không thì sinh cặp Ed25519 vào file nếu chưa có (chạy trước migrate)."""
    if print_env:
        typer.echo(env_lines(*generate_pem_pair()))
        return
    s = get_settings()
    configure_logging("migrate", s)
    result = ensure_keypair(s)
    logger.info("khoá JWT: %s", result, extra={"loc": "auth0002"})
    typer.echo(f"khoá JWT: {result}")


@cli.command("check-config")
def check_config() -> None:
    """Kiểm cấu hình bắt buộc (không cần DB / broker)."""
    problems = get_settings().config_problems()
    for p in problems:
        typer.echo(f"✗ {p}")
    if problems:
        raise typer.Exit(1)
    typer.echo("✓ cấu hình hợp lệ")


@cli.command()
def migrate() -> None:
    """Kiểm cấu hình → Alembic tới head → các bước sau migrate của mọi miền (quyền, role có sẵn, superadmin…)."""
    s = get_settings()
    configure_logging("migrate", s)
    problems = s.config_problems()
    if problems:
        for p in problems:
            logger.error("cấu hình lỗi: %s", p, extra={"loc": "boot0501"})
        raise typer.Exit(1)
    run_migrations(s)
    load_domains()
    asyncio.run(run_post_migrate(s))


@cli.command()
def revision(
    message: str = typer.Option(..., "-m", "--message"),
    autogenerate: bool = typer.Option(True, help="So sánh model với DB để sinh thay đổi"),
) -> None:
    """Tạo revision migration mới."""
    s = get_settings()
    configure_logging("migrate", s)
    typer.echo(str(make_revision(s, message, autogenerate=autogenerate)))


@cli.command("seed-test-users")
def seed_test_users_cmd() -> None:
    """Tạo / làm mới user test (superadmin@, admin@, user1..3@test.local) — từ chối khi ENV=prod hoặc DB thật."""
    s = get_settings()
    configure_logging("migrate", s)
    problem = seed_target_problem(s)
    if problem:
        typer.echo(f"✗ từ chối: {problem}")
        raise typer.Exit(1)
    if SUPERADMIN_SEED_EMAIL not in s.superadmin_emails:
        typer.echo(f"! {SUPERADMIN_SEED_EMAIL} chưa có trong SUPERADMIN_EMAILS — sẽ chỉ là user thường")
    load_domains()
    for row in asyncio.run(seed_test_users(s)):
        mark = "+" if row["created"] else "="
        sup = " superadmin" if row["superadmin"] else ""
        typer.echo(f"{mark} {row['email']} roles={','.join(row['roles'])}{sup}")


@cli.command("dump-openapi")
def dump_openapi(
    out: Path = typer.Option(OPENAPI_FILE, help="File đích (mặc định frontend/src/lib/api/openapi.json)"),
    check: bool = typer.Option(False, help="Chỉ kiểm: file khác bản sinh từ app → exit 1"),
) -> None:
    """Ghi OpenAPI của app `api` — hợp đồng duy nhất giữa backend và frontend (R7)."""
    text = render_openapi(Settings(_env_file=None))  # bỏ .env: file hợp đồng không phụ thuộc máy chạy
    if check:
        if not out.is_file() or out.read_text(encoding="utf-8") != text:
            typer.echo(f"✗ {out} cũ — chạy `make openapi` rồi commit")
            raise typer.Exit(1)
        typer.echo(f"✓ {out} khớp app")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"đã ghi {out}")


async def _dump_chat(s: Settings, session_id: uuid.UUID) -> dict:
    conns = await init_connections("work", s)
    await init_observability(s, conns.mongo)
    try:
        return await dump_session(session_id)
    finally:
        await close_observability()
        await close_connections()


@cli.command("dump-chat-session")
def dump_chat_session(
    session_id: str = typer.Argument(..., help="id phiên chat (agent_sessions.id)"),
    out: Path | None = typer.Option(None, help="File đích; mặc định debug/chat-<id>.json (đã gitignore)"),
) -> None:
    """Gom một phiên chat (phiên, tin nhắn, lượt, duyệt, checkpoint, span trace) vào một JSON — chỉ đọc (R24)."""
    s = get_settings()
    use_settings(s)
    configure_logging("migrate", s)
    sid = uuid.UUID(session_id)
    try:
        data = asyncio.run(_dump_chat(s, sid))
    except LookupError as exc:
        typer.echo(f"✗ {exc}")
        raise typer.Exit(1) from exc
    target = out or Path(__file__).resolve().parents[2] / "debug" / f"chat-{sid}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"đã ghi {target} ({len(data['messages'])} tin nhắn, {len(data['runs'])} lượt)")


async def _agent_eval(s: Settings, limit: int | None) -> list:
    await init_connections("work", s)
    try:
        return await run_eval(s, limit=limit)
    finally:
        await close_connections()


@cli.command("agent-eval")
def agent_eval(
    limit: int = typer.Option(0, help="Chỉ chạy N câu đầu (0 = cả bộ)"),
    as_json: bool = typer.Option(False, "--json", help="In JSON từng câu"),
) -> None:
    """Đo router "Trợ lý" trên bộ ý định tiếng Việt bằng model thật (cần key) — exit 1 khi đúng < 95 %."""
    s = get_settings()
    use_settings(s)
    configure_logging("migrate", s)
    load_domains()
    outcomes = asyncio.run(_agent_eval(s, limit or None))
    rate, misses = report(outcomes)
    if as_json:
        rows = [
            {"text": o.text, "expected": o.expected, "got": o.got, "clarify": o.clarify, "ok": o.ok} for o in outcomes
        ]
        typer.echo(json.dumps(rows, ensure_ascii=False))
    for line in misses:
        typer.echo(line)
    exact = sum(o.exact for o in outcomes)
    n = len(outcomes)
    typer.echo(f"đúng bước đầu {rate:.1%} ({n - len(misses)}/{n}) · khớp hết các bước {exact}/{n}")
    if rate < PASS_RATE:
        raise typer.Exit(1)


credentials_cli = typer.Typer(no_args_is_help=True, help="Khoá mã hoá credential (CREDENTIAL_KEYS)")
cli.add_typer(credentials_cli, name="credentials")


@credentials_cli.command("new-key")
def credentials_new_key() -> None:
    """In một khoá Fernet mới — thêm vào ĐẦU `CREDENTIAL_KEYS` (Coolify) rồi chạy `bw credentials rotate`."""
    typer.echo(new_fernet_key())


async def _rotate(s: Settings) -> int:
    pg = Postgres(s)
    try:
        async with pg.rw() as session:
            return await rotate_all(session, s)
    finally:
        await pg.close()


@credentials_cli.command("rotate")
def credentials_rotate() -> None:
    """Mã hoá lại mọi credential bằng khoá đầu `CREDENTIAL_KEYS` (khoá cũ vẫn phải còn trong danh sách)."""
    s = get_settings()
    configure_logging("migrate", s)
    typer.echo(f"✓ đã mã hoá lại {asyncio.run(_rotate(s))} credential")


def install_outbound(s: Settings) -> list[str]:
    """Bản vá httpx cho process nền — như `api`: log HTTP ra theo LOG_HTTP_OUT, http_capture luôn dùng được."""
    rules = HttpLogRules.from_file(s.resolve_path(s.LOG_HTTP_RULES_FILE))
    return install_httpx_logging(rules, build_keys(s.extra_redact_keys), log=s.LOG_HTTP_OUT)


def _lanes(value: str) -> list[str] | None:
    try:
        return parse_lanes(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _serve(role: str, run: Callable[[Settings, Connections, asyncio.Event], Awaitable[None]]) -> None:
    """Khởi động chung của process nền (log, httpx, miền, kết nối, quan sát, messaging); dừng khi SIGINT / SIGTERM."""

    async def main() -> None:
        s = get_settings()
        use_settings(s)
        configure_logging(role, s)
        install_outbound(s)
        load_domains()
        check_operations()
        conns = await init_connections(role, s)
        await init_observability(s, conns.mongo)
        await start_messaging(s, role)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        logger.info("%s đang chạy", role, extra={"loc": "boot0004"})
        try:
            await run(s, conns, stop)
        finally:
            await stop_messaging()
            await close_observability()
            await close_connections()
            logger.info("%s đã dừng", role, extra={"loc": "boot0005"})

    asyncio.run(main())


@cli.command()
def consume(lanes: str = typer.Option("", help="Lane, phân tách dấu phẩy; trống = mọi lane")) -> None:
    """Chạy consumer FastStream: subscriber + event client `bw.rt.in` của các lane."""
    chosen = _lanes(lanes)
    _serve("consume", lambda s, c, stop: run_consume(s, c, stop=stop, lanes=chosen))


@cli.command()
def work(
    lanes: str = typer.Option("", help="Lane task, phân tách dấu phẩy; trống = mọi lane"),
    concurrency: int = typer.Option(10, help="Số task async chạy đồng thời"),
) -> None:
    """Chạy worker taskiq của các lane; có lane `agent-run` thì nạp sẵn provider LLM trước khi nhận task."""
    chosen = _lanes(lanes)

    async def run(s: Settings, c: Connections, stop: asyncio.Event) -> None:
        if chosen is None or AGENT_LANE in chosen:
            await asyncio.to_thread(warm_providers)
        await run_work(s, c, concurrency, stop=stop, lanes=chosen)

    _serve("work", run)


@cli.command()
def schedule() -> None:
    """Chạy scheduler: task `cron` / `every` + nhịp tim (singleton nhờ khoá leader Redis)."""
    _serve("schedule", lambda s, c, stop: run_schedule(s, c, stop=stop))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
