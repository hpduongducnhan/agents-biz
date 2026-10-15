"""Web Push thuần: vector RFC 8291 Phụ lục A, giải mã vòng tròn, JWT VAPID, header."""

import struct

import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.notifications import webpush
from app.notifications.webpush import (
    RECORD_SIZE,
    b64u,
    encrypt,
    headers,
    new_vapid_keys,
    unb64u,
    vapid_header,
)

AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
PLAIN = b"When I grow up, I want to be a watermelon"
EXPECTED = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3"
    "jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)
ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


def ua_keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, b64u(pub), b64u(bytes(range(16)))


def decrypt(body: bytes, ua_key: ec.EllipticCurvePrivateKey, auth: str) -> bytes:
    """Giải mã phía trình duyệt (RFC 8291 §3.4) để kiểm vòng tròn."""
    salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    as_public, record = body[21 : 21 + idlen], body[21 + idlen :]
    assert rs == RECORD_SIZE and idlen == 65
    ua_public = ua_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    info = b"WebPush: info\x00" + ua_public + as_public
    ikm = HKDF(hashes.SHA256(), 32, unb64u(auth), info).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, record, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_b64u_roundtrip_without_padding():
    for n in range(0, 7):
        raw = bytes(range(n))
        assert "=" not in b64u(raw) and unb64u(b64u(raw)) == raw


def test_rfc8291_appendix_a_vector_exact():
    sender = ec.derive_private_key(int.from_bytes(unb64u(AS_PRIVATE), "big"), ec.SECP256R1())
    body = encrypt(PLAIN, UA_PUBLIC, AUTH, sender=sender, salt=unb64u(SALT))
    assert b64u(body) == EXPECTED


def test_encrypt_roundtrip_with_generated_ua_key():
    key, p256dh, auth = ua_keypair()
    body = encrypt("Xin chào — thông báo".encode(), p256dh, auth)
    assert decrypt(body, key, auth) == "Xin chào — thông báo".encode()
    # mỗi lần mã hoá dùng salt + khoá tạm mới
    assert encrypt(b"x", p256dh, auth) != encrypt(b"x", p256dh, auth)


def test_encrypt_rejects_oversized_payload():
    _, p256dh, auth = ua_keypair()
    with pytest.raises(ValueError, match="quá lớn"):
        encrypt(b"x" * RECORD_SIZE, p256dh, auth)
    assert len(encrypt(b"x" * (RECORD_SIZE - 18), p256dh, auth)) > RECORD_SIZE - 18


def test_new_vapid_keys_are_p256_and_unique():
    a, b = new_vapid_keys(), new_vapid_keys()
    assert a.public_key != b.public_key
    raw = unb64u(a.public_key)
    assert len(raw) == 65 and raw[0] == 4
    assert a.private_pem.startswith("-----BEGIN PRIVATE KEY-----")


def test_vapid_header_jwt_claims_and_signature():
    keys = new_vapid_keys()
    header = vapid_header(f"{ENDPOINT}?x=1", keys, "mailto:a@b.c", now=1_000_000)
    assert header.startswith("vapid t=") and header.endswith(f", k={keys.public_key}")
    token = header.removeprefix("vapid t=").split(", k=")[0]
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(keys.public_key))
    claims = jwt.decode(
        token, pub, algorithms=["ES256"], audience="https://fcm.googleapis.com", options={"verify_exp": False}
    )
    assert claims == {"aud": "https://fcm.googleapis.com", "exp": 1_000_000 + webpush.JWT_TTL, "sub": "mailto:a@b.c"}
    assert jwt.get_unverified_header(token)["alg"] == "ES256"


def test_vapid_header_exp_defaults_to_now_plus_ttl(monkeypatch):
    monkeypatch.setattr(webpush.time, "time", lambda: 5000.0)
    token = vapid_header(ENDPOINT, new_vapid_keys(), "https://x.io").removeprefix("vapid t=").split(", k=")[0]
    assert jwt.decode(token, options={"verify_signature": False})["exp"] == 5000 + webpush.JWT_TTL


def test_headers_defaults_and_overrides():
    keys = new_vapid_keys()
    h = headers(ENDPOINT, keys, "mailto:a@b.c")
    assert h["Content-Encoding"] == "aes128gcm" and h["Content-Type"] == "application/octet-stream"
    assert (h["TTL"], h["Urgency"]) == ("86400", "normal") and h["Authorization"].startswith("vapid t=")
    h2 = headers("https://web.push.apple.com/x", keys, "mailto:a@b.c", ttl=60, urgency="high")
    assert (h2["TTL"], h2["Urgency"]) == ("60", "high")
