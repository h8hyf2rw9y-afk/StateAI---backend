"""
Test env vars must be set before app.core.config.settings (a module-level
singleton) is ever imported — hence this runs before any `from app...`
import below, and before pytest imports any test module.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402, F401 — populates Base.metadata
from app.core.database import get_db  # noqa: E402
from app.core.security import get_current_org_user  # noqa: E402
from app.core.seed_data import FEATURE_SEEDS, ROLE_SEEDS  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.contact import Role  # noqa: E402
from app.models.feature import Feature  # noqa: E402
from app.models.organization import Organization, User  # noqa: E402
from app.schemas.user import CurrentUser  # noqa: E402


@pytest.fixture()
def db_session():
    """
    In-memory SQLite, fresh per test. Excludes app.models.external.auth_users
    from create_all — that stub only exists so ForeignKey("auth.users.id")
    resolves; the real table is Supabase's, never ours to create.

    Foreign keys are explicitly turned on (SQLite disables FK enforcement
    by default, unlike Postgres) so a test that forgets to seed a catalog
    row fails loudly here instead of silently passing and only breaking
    against the real database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))

    own_tables = [t for t in Base.metadata.sorted_tables if t.schema != "auth"]
    Base.metadata.create_all(bind=engine, tables=own_tables)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    session.add_all([Role(**r) for r in ROLE_SEEDS])
    session.add_all([Feature(**f) for f in FEATURE_SEEDS])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def organization_id(db_session) -> uuid.UUID:
    org = Organization(name="Test Realty Group")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org.id


@pytest.fixture()
def current_user(db_session, organization_id) -> CurrentUser:
    """
    A fake authenticated user — bypasses real JWT verification (see
    test_security.py for that in isolation) via get_current_org_user's
    override below, not a real DB lookup. Still backed by a real `users`
    row, though: some entities (e.g. Activity.created_by_user_id) have a
    real foreign key to `users.id`, so `current_user.id` must resolve to an
    actual row for those inserts to succeed, same as it would with a real
    session.
    """
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, organization_id=organization_id, role="agent"))
    db_session.commit()
    return CurrentUser(
        id=user_id,
        email="agent@example.com",
        organization_id=organization_id,
        role="agent",
        provider="email",
    )


@pytest.fixture()
def client(db_session, current_user):
    """A TestClient wired to the in-memory DB and a fake authenticated user — for exercising the CRUD routes without a real Supabase project."""

    def override_get_db():
        yield db_session

    def override_get_current_org_user():
        return current_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = override_get_current_org_user
    yield TestClient(app)
    app.dependency_overrides.clear()
