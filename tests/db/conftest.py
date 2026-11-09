"""PostgreSQL-backed integration test fixtures.

Requires a superuser DSN in ``TEST_ADMIN_DSN`` (e.g. the CI postgres service:
``postgresql://postgres:postgres@localhost:5432/postgres``) plus psql on PATH.
The session fixture creates the production role layout with deploy/postgres/init.sh
(throwaway passwords), then runs the real Alembic migrations for the shop and forge
databases. Tests are skipped, not faked, when the DSN is absent.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DSN = os.environ.get("TEST_ADMIN_DSN")
PASSWORDS = {
    "SHOP_DB_PASSWORD": "t-shop",
    "LAB_DB_PASSWORD": "t-lab",
    "FORGE_DB_PASSWORD": "t-forge",
    "FORGE_READER_DB_PASSWORD": "t-reader",
    "FORGE_REMEDIATOR_DB_PASSWORD": "t-remed",
    "SANDBOX_DB_PASSWORD": "t-sandbox",
}

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="TEST_ADMIN_DSN not set")


def dsn(role: str, password: str, db: str, driver: str = "postgresql+psycopg") -> str:
    host = urlsplit(ADMIN_DSN or "").netloc.split("@")[-1]
    return f"{driver}://{role}:{password}@{host}/{db}"


def _psql(sql: str) -> None:
    subprocess.run(["psql", ADMIN_DSN, "-v", "ON_ERROR_STOP=1", "-qc", sql], check=True)


def _alembic(ini: str, env_var: str, url: str) -> None:
    subprocess.run(["alembic", "-c", ini, "upgrade", "head"], cwd=ROOT, check=True, env={**os.environ, env_var: url})


@pytest.fixture(scope="session")
def databases() -> Iterator[dict[str, str]]:
    if not ADMIN_DSN:
        pytest.skip("TEST_ADMIN_DSN not set")
    for db in ("shop", "lab", "forge", "shop_validation"):
        _psql(f"DROP DATABASE IF EXISTS {db}")
    for role in ("shop_app", "lab_admin", "forge_app", "forge_reader", "forge_remediator", "sandbox_app"):
        _psql(f"DROP ROLE IF EXISTS {role}")
    parts = urlsplit(ADMIN_DSN)
    env = {
        **os.environ,
        **PASSWORDS,
        "POSTGRES_USER": parts.username or "postgres",
        "PGPASSWORD": parts.password or "",
        "PGHOST": parts.hostname or "localhost",
        "PGPORT": str(parts.port or 5432),
    }
    subprocess.run(["bash", str(ROOT / "deploy/postgres/init.sh")], check=True, env=env)
    urls = {
        "shop": dsn("shop_app", "t-shop", "shop"),
        "forge": dsn("forge_app", "t-forge", "forge"),
        "reader": dsn("forge_reader", "t-reader", "shop"),
        "remediator": dsn("forge_remediator", "t-remed", "shop"),
        "sandbox": dsn("sandbox_app", "t-sandbox", "shop_validation"),
        "sandbox_to_shop": dsn("sandbox_app", "t-sandbox", "shop"),
    }
    _alembic("alembic.ini", "SHOP_MIGRATION_DATABASE_URL", urls["shop"])
    _alembic("forge/alembic.ini", "FORGE_MIGRATION_DATABASE_URL", urls["forge"])
    subprocess.run(
        ["python", "-m", "shop.seed"],
        cwd=ROOT,
        check=True,
        env={**os.environ, "SHOP_MIGRATION_DATABASE_URL": urls["shop"]},
    )
    yield urls
