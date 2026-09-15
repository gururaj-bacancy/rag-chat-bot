from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

_engine: Engine | None = None
SessionLocal: sessionmaker | None = None


def get_engine(database_url: str | None = None) -> Engine:
    """Lazily create (or recreate, if `database_url` is passed) the module-level
    SQLAlchemy engine and the `SessionLocal` sessionmaker bound to it.

    Later tasks call `get_engine()` with no args once at import time to ensure
    `SessionLocal` exists, then `from app.db.session import SessionLocal` and
    call `SessionLocal()` to get a session.
    """
    global _engine, SessionLocal

    if _engine is None or database_url is not None:
        _engine = create_engine(database_url or settings.database_url)
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

    return _engine
