"""Database role boundaries, exercised with each component's own credentials."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

pytestmark = pytest.mark.db


def run(url: str, sql: str) -> None:
    with create_engine(url).begin() as conn:
        conn.execute(text(sql))


@pytest.mark.parametrize(
    "role,sql,allowed",
    [
        ("reader", "SELECT count(*) FROM change_events", True),
        ("reader", "SELECT count(*) FROM config_versions", True),
        ("reader", "INSERT INTO change_events(service, kind, summary, actor) VALUES ('x','x','x','x')", False),
        ("reader", "SELECT count(*) FROM orders", False),
        ("remediator", "SELECT count(*) FROM config_versions", True),
        ("remediator", "DELETE FROM config_versions", False),
        ("remediator", "SELECT count(*) FROM orders", False),
        ("remediator", "UPDATE products SET stock = 0", False),
    ],
)
def test_forge_roles_on_shop_db(databases, role, sql, allowed):
    if allowed:
        run(databases[role], sql)
    else:
        with pytest.raises(DBAPIError, match="permission denied"):
            run(databases[role], sql)


def test_sandbox_role_cannot_connect_to_production_shop(databases):
    with pytest.raises(OperationalError, match="permission denied"):
        run(databases["sandbox_to_shop"], "SELECT 1")
