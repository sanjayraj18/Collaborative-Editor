import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database.database import Base

settings = get_settings()


def _database_available() -> bool:
    try:
        engine = create_engine(settings.database_url)
        with engine.connect():
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Postgres not reachable at DATABASE_URL",
)


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    """A session wrapped in a transaction that is always rolled back.

    Every test sees a clean database without truncating tables or ordering
    deletes around foreign keys. Nothing a test writes ever commits.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
