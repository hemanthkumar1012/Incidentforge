"""Alembic environment for the shop database.

The URL comes from SHOP_MIGRATION_DATABASE_URL (sync driver), never from the
ini file, so no credentials are committed.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from shop.models import Base

config = context.config
url = os.environ.get("SHOP_MIGRATION_DATABASE_URL")
if not url:
    raise RuntimeError("SHOP_MIGRATION_DATABASE_URL is not set")
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
