"""GoogleOAuth: PKCE S256 + đổi code / userinfo — HTTP ra Google giả bằng httpx2.MockTransport
(chép $BD/backend/tests/auth/test_google_client.py: đổi đường dẫn module, 1108 → 2108, bỏ picture)."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from app.auth import google as google_mod
from app.core.errors import AppException
from app.core.settings import Settings

VERIFIER = "v" * 64


def oauth() -> google_mod.GoogleOAuth:
    s = Settings(
        _env_file=None,
        GOOGLE_CLIENT_ID="cid",
        GOOGLE_CLIENT_SECRET="secret",
        GOOGLE_REDIRECT_URI="http://localhost/cb",
    )
    return google_mod.GoogleOAuth(s)


@pytest.fixture
def google_http(monkeypatch):
    """Mọi AsyncClient trong module google đi qua transport giả; trả danh sách request đã gửi."""
    sent: list[httpx2.Request] = []
    replies: dict[str, httpx2.Response] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return replies[str(request.url).split("?")[0]]

    real = httpx2.AsyncClient
    monkeypatch.setattr(
        google_mod.httpx2, "AsyncClient", lambda **kw: real(transport=httpx2.MockTransport(handler), **kw)
    )
    return sent, replies


def test_authorize_url_uses_s256_pkce():
    url = urlsplit(oauth().authorize_url("st", VERIFIER))
    q = parse_qs(url.query)
    digest = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
    assert url.netloc == "accounts.google.com"
    assert q["code_challenge"] == [digest] and q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["st"] and q["client_id"] == ["cid"] and q["redirect_uri"] == ["http://localhost/cb"]


async def test_exchange_sends_code_verifier_and_reads_verified_profile(google_http):
    sent, replies = google_http
    replies[google_mod.TOKEN_URL] = httpx2.Response(200, json={"access_token": "at-1"})
    replies[google_mod.USERINFO_URL] = httpx2.Response(
        200, json={"sub": 42, "email": "g@x.io", "email_verified": True, "name": "G", "picture": "http://p"}
    )
    profile = await oauth().exchange("code-1", VERIFIER)
    assert profile == google_mod.GoogleProfile(sub="42", email="g@x.io", name="G")
    token_req, info_req = sent
    form = parse_qs(token_req.content.decode())
    assert form["code_verifier"] == [VERIFIER] and form["grant_type"] == ["authorization_code"]
    assert form["client_secret"] == ["secret"] and form["code"] == ["code-1"]
    assert info_req.headers["authorization"] == "Bearer at-1"


async def test_unverified_email_is_rejected(google_http):
    _, replies = google_http
    replies[google_mod.TOKEN_URL] = httpx2.Response(200, json={"access_token": "at"})
    replies[google_mod.USERINFO_URL] = httpx2.Response(
        200, json={"sub": "1", "email": "g@x.io", "email_verified": False}
    )
    with pytest.raises(AppException) as exc:
        await oauth().exchange("c", VERIFIER)
    assert exc.value.code == 2108


async def test_token_endpoint_error_propagates(google_http):
    sent, replies = google_http
    replies[google_mod.TOKEN_URL] = httpx2.Response(400, json={"error": "invalid_grant"})
    with pytest.raises(httpx2.HTTPStatusError):
        await oauth().exchange("c", VERIFIER)
    assert len(sent) == 1  # không gọi userinfo khi đổi code hỏng
