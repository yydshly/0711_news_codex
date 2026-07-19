from __future__ import annotations

from configparser import ConfigParser
from logging.config import fileConfig
from pathlib import Path

from alembic import context

from newsradar.db.models import Base
from newsradar.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

settings = get_settings()
configured_url = config.get_main_option("sqlalchemy.url")
ini_url = None
if config.config_file_name:
    ini = ConfigParser()
    ini.read(Path(config.config_file_name))
    ini_url = ini.get(config.config_ini_section, "sqlalchemy.url", fallback=None)
if settings.database_url and configured_url == ini_url:
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import engine_from_config, pool

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
