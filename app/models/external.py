"""
Minimal stand-ins for tables Supabase owns and manages (the `auth` schema),
which our `users.id` foreign key needs to reference. SQLAlchemy requires the
referenced table to exist somewhere in Base.metadata to resolve a
ForeignKey — a bare string like "auth.users.id" is not enough on its own.

These are NOT real models: alembic/env.py explicitly excludes anything in
the `auth` schema from autogenerate, so migrations never try to create,
alter, or drop this table. It exists purely so `ForeignKey("auth.users.id")`
in app/models/organization.py resolves correctly.
"""

from sqlalchemy import Column, Table, Uuid

from app.models.base import Base

auth_users = Table(
    "users",
    Base.metadata,
    Column("id", Uuid, primary_key=True),
    schema="auth",
)
