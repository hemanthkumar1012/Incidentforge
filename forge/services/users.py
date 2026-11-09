"""User lookup and bootstrap (database side of identity)."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from forge.db.models import User
from forge.identity import AuthError, hash_password, parse_bootstrap, verify_password


def authenticate(session: Session, username: str, password: str) -> User:
    user = session.scalars(select(User).where(User.username == username)).one_or_none()
    # Hash even for unknown users so response time does not reveal which usernames exist.
    stored = user.password_hash if user else hash_password(secrets.token_hex(8))
    if not verify_password(password, stored) or user is None or user.disabled:
        raise AuthError("invalid username or password")
    return user


def ensure_bootstrap_users(session: Session, spec: str) -> list[str]:
    created = []
    for name, role, password in parse_bootstrap(spec):
        if session.scalars(select(User).where(User.username == name)).first() is None:
            session.add(User(username=name, role=role.value, password_hash=hash_password(password)))
            created.append(name)
    return created
