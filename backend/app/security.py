"""Password hashing (stdlib scrypt), API tokens and secret encryption."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
TOKEN_PREFIX = "sav_"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def new_api_token() -> tuple[str, str, str]:
    """Return ``(token, sha256_hash, display_prefix)``; only the hash is stored."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token), token[:10]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SecretBox:
    """Fernet encryption for provider API keys, keyed from ``SAV_SECRET_KEY``."""

    def __init__(self, secret_key: str):
        key = base64.urlsafe_b64encode(hashlib.sha256(("sav-secrets:" + secret_key).encode()).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise ValueError("cannot decrypt secret (SAV_SECRET_KEY changed?)") from exc


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "…" + value[-4:]
