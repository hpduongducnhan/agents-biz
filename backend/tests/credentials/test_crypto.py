"""Mã hoá credential: Fernet nhiều khoá, xoay khoá, che giá trị, thiếu khoá ở prod / dev."""

import pytest

from app.core.errors import AppException
from app.core.settings import Settings
from app.credentials import crypto


def cfg(base: Settings, keys: str, env: str = "dev") -> Settings:
    return base.model_copy(update={"CREDENTIAL_KEYS": keys, "ENV": env})


@pytest.fixture(autouse=True)
def reset_ephemeral():
    crypto._state["ephemeral"] = None
    yield
    crypto._state["ephemeral"] = None


def test_encrypt_decrypt_roundtrip_and_rotation(test_settings):
    a, b = crypto.new_key(), crypto.new_key()
    only_a = cfg(test_settings, a)
    cipher, kid = crypto.encrypt("sk-secret-value-1234", only_a)
    assert kid == crypto.key_id(a.encode()) and "secret" not in cipher
    assert crypto.decrypt(cipher, only_a) == "sk-secret-value-1234"
    both = cfg(test_settings, f"{b}, {a}")  # khoá mới đứng đầu, khoá cũ vẫn giải mã được
    assert crypto.decrypt(cipher, both) == "sk-secret-value-1234"
    cipher2, kid2 = crypto.encrypt("sk-secret-value-1234", both)
    assert kid2 == crypto.key_id(b.encode()) != kid
    assert crypto.decrypt(cipher2, both) == "sk-secret-value-1234"
    with pytest.raises(AppException) as exc:  # khoá cũ bị gỡ khỏi danh sách → không giải mã được
        crypto.decrypt(cipher, cfg(test_settings, b))
    assert exc.value.code == 6016


def test_mask_hides_secret():
    assert crypto.mask("sk-abcdef1234") == "sk-…1234"
    assert crypto.mask("abcdefghij1234") == "ab…1234"
    assert crypto.mask("short") == "…"
    assert crypto.mask("  ") == "…"


def test_keys_ready_and_configured_keys(test_settings):
    assert crypto.keys_ready(cfg(test_settings, "", "dev"))
    assert not crypto.keys_ready(cfg(test_settings, "", "prod"))
    assert crypto.keys_ready(cfg(test_settings, crypto.new_key(), "prod"))
    assert crypto.configured_keys(cfg(test_settings, " a , ,b ")) == [b"a", b"b"]


def test_prod_without_keys_is_6016(test_settings):
    prod = cfg(test_settings, "", "prod")
    with pytest.raises(AppException) as exc:
        crypto.encrypt("sk-x", prod)
    assert exc.value.code == 6016 and exc.value.status_code == 503
    with pytest.raises(AppException):
        crypto.decrypt("whatever", prod)


def test_dev_without_keys_generates_ephemeral_once(test_settings, bw_log):
    dev = cfg(test_settings, "", "dev")
    cipher, kid = crypto.encrypt("sk-dev-secret-9999", dev)
    assert crypto.decrypt(cipher, dev) == "sk-dev-secret-9999"
    crypto.encrypt("again", dev)
    warns = [r for r in bw_log() if r.get("loc") == "cred0001"]
    assert len(warns) == 1 and "DEFAULTS_APPLIED=[CREDENTIAL_KEYS]" in warns[0]["msg"]
    assert kid == crypto.key_id(crypto._state["ephemeral"])
