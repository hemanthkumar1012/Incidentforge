"""Alembic environment for the forge (control-plane) database."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

url = os.environ.get("FORGE_MIGRATION_DATABASE_URL")
if not url:
    raise RuntimeError("FORGE_MIGRATION_DATABASE_URL is not set")

if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, poolclass=pool.NullPool).connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
