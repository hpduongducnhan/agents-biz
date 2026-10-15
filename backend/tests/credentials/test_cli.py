"""`bw credentials new-key | rotate`."""

import psycopg
import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from app import cli as cli_module
from app.cli import cli
from app.core.connections.postgres import Postgres
from app.core.migrate import run_migrations
from app.credentials import crypto
from app.credentials.models import Credential
from app.credentials.service import seal
from tests.conftest import plain_dsn, reset_test_db

runner = CliRunner()


def test_cli_new_key():
    out = runner.invoke(cli, ["credentials", "new-key"])
    assert out.exit_code == 0
    Fernet(out.output.strip().encode())  # khoá Fernet hợp lệ
    assert out.output.strip() != runner.invoke(cli, ["credentials", "new-key"]).output.strip()


@pytest.mark.integration
async def test_cli_rotate_reencrypts_on_test_db(test_settings, monkeypatch):
    old, new = crypto.new_key(), crypto.new_key()
    seeded = test_settings.model_copy(update={"CREDENTIAL_KEYS": old, "MONGO_ENABLED": False})
    reset_test_db(seeded)
    run_migrations(seeded)
    pg = Postgres(seeded)
    async with pg.rw() as s:
        for i in range(2):
            c = Credential(name=f"c{i}", secret_ciphertext="", key_id="", masked_hint="")
            seal(c, f"sk-value-{i}-abcdef", seeded)
            s.add(c)
    await pg.close()
    rotated = seeded.model_copy(update={"CREDENTIAL_KEYS": f"{new},{old}"})
    monkeypatch.setattr(cli_module, "get_settings", lambda: rotated)
    result = await __import__("asyncio").to_thread(runner.invoke, cli, ["credentials", "rotate"])
    assert result.exit_code == 0 and "2 credential" in result.output
    with psycopg.connect(plain_dsn(rotated)) as conn:
        ids = {r[0] for r in conn.execute("select key_id from credentials")}
    assert ids == {crypto.key_id(new.encode())}
