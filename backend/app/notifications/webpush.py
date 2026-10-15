"""Web Push chuẩn không thư viện ngoài: khoá VAPID P-256, JWT VAPID (RFC 8292)
ký ES256 bằng pyjwt, mã hoá `aes128gcm` (RFC 8291 + RFC 8188) bằng `cryptography`. Hàm thuần — không DB / mạng."""

from __future__ import annotations

import base64
import os
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096
JWT_TTL = 12 * 3600


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


@dataclass(frozen=True)
class VapidKeys:
    private_pem: str  # PKCS8 PEM của khoá riêng P-256
    public_key: str  # base64url 65 byte (điểm không nén) — applicationServerKey của trình duyệt


def new_vapid_keys() -> VapidKeys:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return VapidKeys(private_pem=pem.decode(), public_key=b64u(_raw_public(key.public_key())))


def vapid_header(endpoint: str, keys: VapidKeys, subject: str, now: float | None = None) -> str:
    """`Authorization: vapid t=<JWT>, k=<khoá công khai>` — `aud` = origin của push service."""
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + JWT_TTL), "sub": subject}
    token = jwt.encode(claims, keys.private_pem, algorithm="ES256", headers={"typ": "JWT"})
    return f"vapid t={token}, k={keys.public_key}"


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(
    payload: bytes,
    p256dh: str,
    auth: str,
    *,
    sender: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """Thân request `aes128gcm` cho một đăng ký: header (salt · rs · keyid = khoá công khai tạm) + một bản ghi mã hoá.
    `sender` / `salt` chỉ truyền khi kiểm bằng vector của RFC 8291 §5."""
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = _raw_public(sender.public_key())
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = sender.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    if len(payload) > RECORD_SIZE - 17 - 1:
        raise ValueError("payload quá lớn cho một bản ghi Web Push")
    record = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # 0x02 = bản ghi cuối, không đệm
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + record


def headers(
    endpoint: str, keys: VapidKeys, subject: str, *, ttl: int = 86400, urgency: str = "normal"
) -> dict[str, str]:
    return {
        "Authorization": vapid_header(endpoint, keys, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": urgency,
    }
