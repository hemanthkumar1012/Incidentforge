"""allow the fixed-summary LLM baseline mode

Revision ID: f0002
Revises: f0001
Create Date: 2026-11-08
"""

from alembic import op

revision = "f0002"
down_revision = "f0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE investigations DROP CONSTRAINT investigations_mode_check")
    op.execute(
        "ALTER TABLE investigations ADD CONSTRAINT investigations_mode_check "
        "CHECK (mode IN ('llm', 'runbook', 'llm_summary'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE investigations DROP CONSTRAINT investigations_mode_check")
    op.execute("ALTER TABLE investigations ADD CONSTRAINT investigations_mode_check CHECK (mode IN ('llm', 'runbook'))")
