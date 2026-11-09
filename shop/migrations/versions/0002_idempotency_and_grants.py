"""idempotent reservations, request fingerprints, least-privilege grants

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08

* reservations.order_ref becomes unique (one hold per order) so a retried
  reserve cannot decrement stock twice.
* orders.request_fingerprint lets checkout reject a reused idempotency key
  that arrives with a different body.
* Table-level grants replace the broad default privileges the lab used to
  have. Roles are created by deploy/postgres/init.sh; each grant is skipped
  when its role does not exist (for example in a bare test database).
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# role -> (privileges, tables)
GRANTS: dict[str, list[tuple[str, str]]] = {
    # Incident Lab: injects config faults and restores the baseline.
    "lab_admin": [("SELECT, INSERT, UPDATE", "config_versions, change_events")],
    # Investigator telemetry adapter: change history and config versions only.
    "forge_reader": [("SELECT", "config_versions, change_events")],
    # Remediation executor: writes new config versions through config_admin.
    "forge_remediator": [("SELECT, INSERT, UPDATE", "config_versions, change_events")],
}
SEQUENCES = "config_versions_id_seq, change_events_id_seq"


def _grant_if_role_exists(role: str, statement: str) -> None:
    # Role and table names come from the constants above, never from input.
    guard = f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')"  # noqa: S608
    op.execute(f"DO $$ BEGIN {guard} THEN EXECUTE '{statement}'; END IF; END $$;")


def upgrade() -> None:
    op.drop_index("ix_reservations_order_ref", table_name="reservations")
    op.create_unique_constraint("uq_reservations_order_ref", "reservations", ["order_ref"])
    op.add_column("orders", sa.Column("request_fingerprint", sa.String(64)))

    for role, grants in GRANTS.items():
        _grant_if_role_exists(role, f"GRANT USAGE ON SCHEMA public TO {role}")
        for privileges, tables in grants:
            _grant_if_role_exists(role, f"GRANT {privileges} ON {tables} TO {role}")
        if "INSERT" in "".join(p for p, _ in grants):
            _grant_if_role_exists(role, f"GRANT USAGE, SELECT ON SEQUENCE {SEQUENCES} TO {role}")


def downgrade() -> None:
    for role in GRANTS:
        _grant_if_role_exists(role, f"REVOKE ALL ON config_versions, change_events FROM {role}")
    op.drop_column("orders", "request_fingerprint")
    op.drop_constraint("uq_reservations_order_ref", "reservations", type_="unique")
    op.create_index("ix_reservations_order_ref", "reservations", ["order_ref"])
