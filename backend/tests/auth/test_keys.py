"""`bw keys`: cặp khoá JWT tự sinh vào file lần đầu (local), hoặc lấy PEM từ env (ưu tiên env — Coolify)."""

import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

from app.auth.keys import ensure_keypair, env_lines, generate_pem_pair
from app.core.settings import Settings


def _settings(tmp_path: Path, **kw) -> Settings:
    base = {
        "AUTH_PRIVATE_KEY_FILE": str(tmp_path / "keys" / "jwt_private.pem"),
        "AUTH_PUBLIC_KEY_FILE": str(tmp_path / "keys" / "jwt_public.pem"),
    }
    return Settings(_env_file=None, **(base | kw))


def test_generates_pair_once_and_rerun_is_idempotent(tmp_path):
    s = _settings(tmp_path)
    assert ensure_keypair(s) == "generated"
    priv, pub = Path(s.AUTH_PRIVATE_KEY_FILE), Path(s.AUTH_PUBLIC_KEY_FILE)
    assert stat.S_IMODE(priv.stat().st_mode) == 0o600 and stat.S_IMODE(pub.stat().st_mode) == 0o644
    load_pem_private_key(priv.read_bytes(), password=None)
    load_pem_public_key(pub.read_bytes())
    before = priv.read_bytes()
    assert ensure_keypair(s) == "exists" and priv.read_bytes() == before  # chạy lại `make migrate` không đổi khoá


def test_pem_in_env_wins_and_writes_nothing(tmp_path, auth_keys):
    priv, pub = (Path(p).read_text() for p in auth_keys)
    s = _settings(tmp_path, AUTH_PRIVATE_KEY=priv, AUTH_PUBLIC_KEY=pub)
    assert ensure_keypair(s) == "env"
    assert not (tmp_path / "keys").exists()


def test_env_lines_round_trip_through_settings(tmp_path):
    private_pem, public_pem = generate_pem_pair()
    lines = env_lines(private_pem, public_pem).splitlines()
    assert [line.split("=", 1)[0] for line in lines] == ["AUTH_PRIVATE_KEY", "AUTH_PUBLIC_KEY"]
    env = dict(line.split("=", 1) for line in lines)
    s = _settings(tmp_path, **env)  # một dòng có `\n` như dán vào Coolify
    key = load_pem_private_key(s.AUTH_PRIVATE_KEY.encode(), password=None)
    assert s.AUTH_PUBLIC_KEY == public_pem.decode().strip()
    assert key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo) == public_pem
    assert _settings(tmp_path, AUTH_PRIVATE_KEY=private_pem.decode()).AUTH_PRIVATE_KEY == private_pem.decode().strip()


def test_pem_escaped_twice_or_with_stray_backslash_restored(tmp_path):
    _, public_pem = generate_pem_pair()
    pem = public_pem.decode().strip()
    for variant in (
        pem.replace("\n", "\\\\n"),  # Coolify escape thêm một lần: `\\n`
        pem.replace("\n", "\\\n"),  # dotenv đã đổi `\n` → xuống dòng nhưng còn sót `\`
    ):
        s = _settings(tmp_path, AUTH_PUBLIC_KEY=variant)
        assert s.AUTH_PUBLIC_KEY == pem
        load_pem_public_key(s.AUTH_PUBLIC_KEY.encode())


def test_half_configured_keys_fail_loudly(tmp_path, auth_keys):
    priv = Path(auth_keys[0]).read_text()
    with pytest.raises(RuntimeError, match="cùng nhau"):
        ensure_keypair(_settings(tmp_path, AUTH_PRIVATE_KEY=priv))
    s = _settings(tmp_path)
    Path(s.AUTH_PRIVATE_KEY_FILE).parent.mkdir(parents=True)
    Path(s.AUTH_PRIVATE_KEY_FILE).write_text(priv)
    with pytest.raises(RuntimeError, match="một file"):
        ensure_keypair(s)
    with pytest.raises(RuntimeError, match="AUTH_PRIVATE_KEY_FILE"):
        ensure_keypair(Settings(_env_file=None, AUTH_PRIVATE_KEY_FILE="", AUTH_PUBLIC_KEY_FILE=""))
