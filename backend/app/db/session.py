from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine: Engine | None = None
SessionLocal: sessionmaker | None = None


def get_engine(database_url: str | None = None) -> Engine:
    """Lazily create (or recreate, if `database_url` is passed) the module-level
    SQLAlchemy engine and the `SessionLocal` sessionmaker bound to it.

    IMPORTANT — do not do `from app.db.session import SessionLocal` at another
    module's import time and hold onto that name. `SessionLocal` is reassigned
    in place by this function (e.g. tests call `get_engine(settings.test_database_url)`
    in a session-scoped fixture to point it at the test DB). A name bound via
    `from ... import SessionLocal` at import time — which, for a module
    imported during pytest collection, happens *before* that fixture runs —
    captures whatever `SessionLocal` was at that instant and never sees the
    reassignment, silently pinning that consumer to the wrong database.

    Callers should either:
      - use `get_session()` below, which always looks up the current
        `SessionLocal` at call time, or
      - do `from app.db import session as db_session` and reference
        `db_session.SessionLocal()` at call time (module-attribute lookup,
        not a bare name import).
    """
    global _engine, SessionLocal

    if _engine is None or database_url is not None:
        _engine = create_engine(database_url or settings.database_url)
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

    return _engine


def get_session() -> Session:
    """Return a fresh session from the current `SessionLocal`.

    This is the recommended way for later tasks (FastAPI dependencies,
    scripts, etc.) to obtain a session: it always resolves `SessionLocal` at
    call time via `get_engine()`, so it can't go stale the way a module-level
    `from app.db.session import SessionLocal` import can (see `get_engine`'s
    docstring). Ensures the engine/sessionmaker exist first by calling
    `get_engine()` with no args, which is a no-op once already initialized.
    """
    get_engine()
    return SessionLocal()
