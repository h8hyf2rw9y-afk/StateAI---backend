from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Sync engine — see the plan's rationale for sync over async at this stage.
# pool_pre_ping guards against Supabase closing idle connections underneath us.
engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped DB session, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
