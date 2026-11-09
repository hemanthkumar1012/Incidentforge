"""Request-scoped dependencies: one DB transaction per request, authenticated actor, permissions."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from forge.db.models import User
from forge.domain.policy import Actor, Permission, Role, has_permission
from forge.identity import AuthError, decode_token
from forge.services.common import Forbidden, ServiceError
from forge.wiring import Container


class Unauthorized(ServiceError):
    status_code, code = 401, "unauthorized"


def container(request: Request) -> Container:
    return request.app.state.container


def db(c: Container = Depends(container)) -> Iterator[Session]:
    """Commit if the handler returns, roll back if it raises."""
    with c.sessions.begin() as session:
        yield session


def current_actor(
    authorization: str = Header(default=""), session: Session = Depends(db), c: Container = Depends(container)
) -> Actor:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("missing bearer token")
    try:
        username = decode_token(token, c.settings.jwt_secret)
    except AuthError as exc:
        raise Unauthorized(str(exc)) from exc
    user = session.query(User).filter_by(username=username).one_or_none()
    if user is None or user.disabled:
        raise Unauthorized("user is unknown or disabled")
    return Actor(user.username, Role(user.role))


def require(permission: Permission) -> Callable[[Actor], Actor]:
    def check(actor: Actor = Depends(current_actor)) -> Actor:
        if not has_permission(actor.role, permission):
            raise Forbidden(f"role {actor.role} lacks permission {permission}", details={"required": permission.value})
        return actor

    return check
