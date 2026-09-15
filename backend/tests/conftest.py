import pytest
from sqlalchemy import text

from app.config import settings
from app.db import session as db_session_module
from app.db.models import Base
from app.db.session import get_engine
from scripts.run_migrations import run_migrations


@pytest.fixture(scope="session", autouse=True)
def _setup_test_db():
    get_engine(settings.test_database_url)
    run_migrations(settings.test_database_url)


@pytest.fixture
def db_session(_setup_test_db):
    # Note: `SessionLocal` is (re)assigned inside app.db.session by get_engine(),
    # so it must be accessed via the module rather than an early-bound `from
    # app.db.session import SessionLocal`, which would capture the pre-setup
    # value (None).
    with db_session_module.SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
        session.commit()

    session = db_session_module.SessionLocal()
    try:
        yield session
    finally:
        session.close()
