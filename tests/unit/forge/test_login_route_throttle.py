from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from forge.api import app as app_module  # noqa: E402
from forge.api.deps import container, db  # noqa: E402
from forge.api.throttle import LoginThrottle  # noqa: E402
from forge.identity import AuthError  # noqa: E402


class Clock:
    def __call__(self) -> float:
        return 1000.0


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    c = SimpleNamespace(
        login_throttle=LoginThrottle(per_user_limit=2, clock=Clock()),
        settings=SimpleNamespace(jwt_secret="s" * 32),
    )

    def fake_auth(_s: object, username: str, password: str) -> SimpleNamespace:
        if password != "right":
            raise AuthError("invalid credentials")
        return SimpleNamespace(username=username, role="viewer")

    monkeypatch.setattr(app_module, "authenticate", fake_auth)
    monkeypatch.setattr(app_module, "issue_token", lambda *_a: "tok")
    app_module.app.dependency_overrides[container] = lambda: c
    app_module.app.dependency_overrides[db] = lambda: MagicMock()
    yield TestClient(app_module.app)
    app_module.app.dependency_overrides.clear()


def test_login_returns_429_with_retry_after_after_repeated_failures(client: TestClient) -> None:
    for _ in range(2):
        assert client.post("/api/auth/login", json={"username": "u", "password": "bad"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "u", "password": "bad"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert r.json()["error"]["code"] == "too_many_requests"


def test_blocked_user_cannot_login_even_with_correct_password(client: TestClient) -> None:
    for _ in range(2):
        client.post("/api/auth/login", json={"username": "u", "password": "bad"})
    assert client.post("/api/auth/login", json={"username": "u", "password": "right"}).status_code == 429


def test_successful_login_unaffected(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "ok", "password": "right"})
    assert r.status_code == 200
    assert r.json()["access_token"] == "tok"
