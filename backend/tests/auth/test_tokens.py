"""Mật khẩu argon2id + JWT EdDSA với đúng claims BizWithAgents (sub · typ · perms · sup · iat · exp)."""

import time
import uuid
from pathlib import Path

import jwt
import pytest

from app.auth.passwords import DUMMY_HASH, check_password_policy, hash_password, verify_password
from app.auth.tokens import TokenService, hash_token, new_refresh_token
from app.core.errors import AppException


def test_password_hash_roundtrip_and_bad_hash():
    h = hash_password("s3cret-pass")
    assert h.startswith("$argon2id$") and verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "") and not verify_password("x", None) and not verify_password("x", "not-a-hash")
    assert DUMMY_HASH.startswith("$argon2id$") and not verify_password("password123", DUMMY_HASH)


def test_password_policy_2107():
    check_password_policy("12345678", 8)
    with pytest.raises(AppException) as err:
        check_password_policy("1234567", 8)
    assert (err.value.code, err.value.status_code) == (2107, 422)


def test_access_token_carries_only_bizwithagents_claims(test_settings):
    svc = TokenService(test_settings)
    uid = uuid.uuid4()
    tid = uuid.uuid4()
    token, expires_in = svc.issue_access(
        user_id=uid, sup=False, perms=["user.view", "agent.chat", "user.view"], tenant_id=tid
    )
    claims = svc.decode_access(token)
    assert set(claims) == {"sub", "tid", "typ", "perms", "sup", "iat", "exp"}
    assert claims["tid"] == str(tid)
    assert (claims["sub"], claims["typ"], claims["sup"]) == (str(uid), "access", False)
    assert claims["perms"] == ["agent.chat", "user.view"]
    assert claims["exp"] - claims["iat"] == 1800 == expires_in
    assert jwt.get_unverified_header(token)["alg"] == "EdDSA"


def test_superadmin_token_has_no_perms(test_settings):
    svc = TokenService(test_settings)
    token, _ = svc.issue_access(user_id=uuid.uuid4(), sup=True, perms={"user.view"})
    claims = svc.decode_access(token)
    assert claims["sup"] is True and claims["perms"] == []


def test_tampered_expired_or_wrong_type_token_is_401(test_settings):
    svc = TokenService(test_settings)
    token, _ = svc.issue_access(user_id=uuid.uuid4(), sup=False, perms=())
    with pytest.raises(AppException) as err:
        svc.decode_access(token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB"))
    assert (err.value.code, err.value.status_code) == (1004, 401)
    expired = TokenService(test_settings.model_copy(update={"AUTH_ACCESS_TOKEN_EXPIRE_MINUTES": -1}))
    old, _ = expired.issue_access(user_id=uuid.uuid4(), sup=False, perms=())
    with pytest.raises(AppException):
        svc.decode_access(old)
    now = int(time.time())
    refresh_like = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "refresh", "iat": now, "exp": now + 60}, svc.private_key, algorithm="EdDSA"
    )
    with pytest.raises(AppException):
        svc.decode_access(refresh_like)


def test_refresh_token_random_and_hashed():
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b and len(a) >= 60
    assert hash_token(a) == hash_token(a) != hash_token(b) and len(hash_token(a)) == 64


def test_decode_needs_only_public_key(test_settings):
    uid = uuid.uuid4()
    token, _ = TokenService(test_settings).issue_access(user_id=uid, sup=False, perms=())
    verifier = TokenService(test_settings.model_copy(update={"AUTH_PRIVATE_KEY_FILE": "/nonexistent.pem"}))
    assert verifier.decode_access(token)["sub"] == str(uid)


def test_pem_from_env_wins_over_files(test_settings, auth_keys):
    priv, pub = (Path(p).read_text() for p in auth_keys)
    env_only = test_settings.model_copy(
        update={
            "AUTH_PRIVATE_KEY_FILE": "/nonexistent.pem",
            "AUTH_PUBLIC_KEY_FILE": "/nonexistent.pem",
            "AUTH_PRIVATE_KEY": priv.replace("\n", "\\n"),  # env một dòng: xuống dòng viết dạng \n
            "AUTH_PUBLIC_KEY": pub,
        }
    )
    svc = TokenService(env_only)
    token, _ = svc.issue_access(user_id=uuid.uuid4(), sup=False, perms=())
    assert svc.decode_access(token)["typ"] == "access"
