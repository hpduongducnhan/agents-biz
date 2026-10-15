"""Đăng nhập Google: OAuth 2 authorization code + PKCE, gọi Google bằng httpx2 (B19)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx2

from app.core.errors import AppException
from app.core.settings import Settings

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass(frozen=True)
class GoogleProfile:
    sub: str
    email: str
    name: str = ""


def code_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class GoogleOAuth:
    def __init__(self, settings: Settings) -> None:
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    def authorize_url(self, state: str, verifier: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange(self, code: str, verifier: str) -> GoogleProfile:
        async with httpx2.AsyncClient(timeout=10) as client:
            token = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
            token.raise_for_status()
            info = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {token.json()['access_token']}"})
            info.raise_for_status()
        data = info.json()
        if not data.get("email") or not data.get("email_verified"):
            raise AppException(2108, status_code=400, detail="Google account email is not verified")
        return GoogleProfile(sub=str(data["sub"]), email=data["email"], name=data.get("name", ""))
