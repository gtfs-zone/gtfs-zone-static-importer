"""Test database and a fake object store.

SQLite in memory and moto, so the suite needs no running service. Migrations
are not covered here; they live in gtfs-zone-db-models and are round-tripped against
the dev database by hand.
"""

from __future__ import annotations

import contextlib
import io
import zipfile

import boto3
import gtfs_zone_db_models.models  # noqa: F401 - registers every table on the metadata
import pytest
from gtfs_zone_db_models.object_store import ObjectStore, ObjectStoreSettings
from moto import mock_aws
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

BUCKET = "test-feeds"
# Not an AWS hostname on purpose: the store points at Garage, and moto only
# intercepts a custom endpoint when told which one.
ENDPOINT = "http://s3.local"


@pytest.fixture
def engine():
    # StaticPool: every `sqlite://` connection otherwise opens its own empty
    # in-memory database, so tables created on one are invisible to the next.
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(engine, monkeypatch):
    """`get_session` as the tasks see it, bound to the test database.

    Patched on `gtfs_zone_static_importer.tasks` rather than on `database`, because the
    task module imported the name at import time.
    """

    @contextlib.contextmanager
    def get_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr("gtfs_zone_static_importer.tasks.get_session", get_session)
    return get_session


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", ENDPOINT)
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        store = ObjectStore(
            ObjectStoreSettings(
                s3_endpoint=ENDPOINT,
                s3_bucket=BUCKET,
                s3_access_key="key",
                s3_secret_key="secret",
                s3_region="us-east-1",
            )
        )
        # `get_object_store` is lru_cached and reads the process environment;
        # handing the fake back directly keeps the cache out of the test.
        monkeypatch.setattr(
            "gtfs_zone_static_importer.gtfs_loader.get_object_store", lambda: store
        )
        yield store


def make_gtfs_zip(*, route_id: str = "R1") -> bytes:
    """The smallest zip `load_feed_data` reads something out of."""
    files = {
        "agency.txt": (
            "agency_id,agency_name,agency_timezone\nA,Agency,America/New_York\n"
        ),
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS1,Stop One,40.0,-74.0\n",
        "routes.txt": (
            "route_id,agency_id,route_short_name,route_long_name,route_type\n"
            f"{route_id},A,1,One,3\n"
        ),
        "trips.txt": f"route_id,service_id,trip_id,direction_id\n{route_id},SVC,T1,0\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
            "start_date,end_date\n"
            "SVC,1,1,1,1,1,1,1,20250101,20261231\n"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buffer.getvalue()
