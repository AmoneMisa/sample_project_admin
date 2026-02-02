from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from src.db.base import Base
from src.models import models

target_metadata = Base.metadata


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.
import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
load_dotenv("db.env")

def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default

def make_url():
    host = _env("DB_HOST", "localhost")
    port = _env("DB_PORT", "3306")
    user = _env("MARIADB_USER", "root")
    password = _env("MARIADB_PASSWORD", "")
    db = _env("MARIADB_DATABASE", "")

    if not db:
        raise RuntimeError("MARIADB_DATABASE is empty. Set it in .env")

    password = quote_plus(password)

    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"



def run_migrations_offline() -> None:
    url = make_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    config.set_main_option("sqlalchemy.url", make_url())
    print("ALEMBIC DB URL:", config.get_main_option("sqlalchemy.url"))

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()



if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
