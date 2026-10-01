from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from gtfs_zone_static_importer.settings import settings

_engine: Engine | None = None


def _get_engine() -> Engine:
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
def get_session() -> Iterator[Session]:
    with Session(_get_engine()) as session:
        yield session
