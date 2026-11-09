"""Local users, password hashing and access tokens.

* Passwords: ``hashlib.scrypt`` (memory-hard, stdlib) with a per-user salt,
  compared in constant time. Format: ``scrypt$n$r$p$salt_hex$hash_hex``.
* Tokens: HS256 JWTs with ``sub``, ``role``, ``iat``, ``exp`` (8 h). The role is
  re-read from the database on every request, so disabling a user or changing a
  role takes effect immediately rather than when the token expires.
* Bootstrap parsing for ``FORGE_BOOTSTRAP_USERS="name:role:password,..."``; the
  database side lives in forge/services/users.py.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from forge.domain.policy import Role

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
TOKEN_TTL = timedelta(hours=8)
ALGORITHM = "HS256"


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt_hex),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(hash_hex) // 2,
    )
    return hmac.compare_digest(digest.hex(), hash_hex)


def issue_token(username: str, role: str, secret: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + TOKEN_TTL).timestamp()),
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> str:
    """Return the username in a valid token or raise ``AuthError``."""
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["sub", "exp", "iat"]})
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid token") from exc
    return str(claims["sub"])


def parse_bootstrap(spec: str) -> list[tuple[str, Role, str]]:
    users = []
    for entry in filter(None, (e.strip() for e in spec.split(","))):
        name, role, password = entry.split(":", 2)
        if len(password) < 12:
            raise ValueError(f"bootstrap password for {name} must be at least 12 characters")
        users.append((name, Role(role), password))
    return users
