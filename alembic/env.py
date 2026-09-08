from logging.config import fileConfig

from sqlalchemy import create_engine
from sqlalchemy import pool

from alembic import context

# Import every model so Base.metadata is fully populated before autogenerate
# inspects it — see app/models/__init__.py's docstring for why this matters.
import app.models  # noqa: F401
from app.core.config import settings
from app.models.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# DATABASE_URL comes from our own Settings (.env / real env vars) and is
# used directly below (create_engine / context.configure(url=...)) rather
# than routed through config.set_main_option — configparser's default
# interpolation treats a bare "%" as the start of a %(...)s reference, which
# breaks on a percent-encoded password (e.g. "%40" for "@") unless doubled
# to "%%". Passing the URL straight to SQLAlchemy sidesteps that entirely.

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """
    Excludes anything in the `auth` schema (Supabase's own tables) from
    autogenerate — app.models.external.auth_users exists only so our
    `users.id` foreign key resolves; Supabase already owns and migrates
    that table, so we must never generate CREATE/ALTER/DROP for it.
    """
    return getattr(object, "schema", None) != "auth"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
