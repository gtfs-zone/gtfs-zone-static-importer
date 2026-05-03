from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from schedule_foamer.settings import settings

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # handles DB container restarts
        )
    return _engine


@contextmanager
def get_session():
    with Session(_get_engine()) as session:
        yield session
