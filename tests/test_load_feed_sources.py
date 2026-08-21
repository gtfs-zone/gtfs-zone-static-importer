"""`load_feed` against both source kinds, and what the beat sweep picks up."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from railroad_club.models import Feed, GtfsRoute, GtfsStaticFeed, LoadStatus, User
from railroad_club.models.gtfs_upload import (
    FeedSourceKind,
    GtfsUpload,
    object_key_for,
)
from railroad_club.object_store import ObjectNotFound
from sqlalchemy import select
from sqlalchemy.orm import Session

from schedule_foamer import tasks
from tests.conftest import make_gtfs_zip


def _now():
    return datetime.now(UTC)


def _owner(session: Session) -> User:
    user = User(primary_email="owner@example.com")
    session.add(user)
    session.commit()
    return user


def make_feed(engine, *, hosted: bool, with_upload: bool = True, **kwargs) -> int:
    """A feed of one kind or the other, and its stored zip if it is hosted."""
    with Session(engine) as session:
        owner = _owner(session)
        feed = Feed(
            feed_name=kwargs.pop("feed_name", "test-feed"),
            owner_id=owner.id,
            source_kind=FeedSourceKind.hosted if hosted else FeedSourceKind.url,
            static_feed_url=None if hosted else "https://example.com/gtfs.zip",
            **kwargs,
        )
        session.add(feed)
        session.commit()
        if hosted and with_upload:
            upload = GtfsUpload(
                feed_id=feed.id,
                object_key="",
                sha256="0" * 64,
                size_bytes=1,
                original_filename="gtfs.zip",
            )
            upload.object_key = object_key_for(feed.id, upload.id)
            session.add(upload)
            session.commit()
            feed.current_upload_id = upload.id
            session.commit()
        return feed.id


def static_feed(engine, feed_id: int) -> GtfsStaticFeed:
    with Session(engine) as session:
        feed = session.get(Feed, feed_id)
        return session.get(GtfsStaticFeed, feed.gtfs_static_feed_id)


def test_hosted_feed_loads_from_the_store(engine, session_factory, store):
    feed_id = make_feed(engine, hosted=True)
    with Session(engine) as session:
        key = session.get(Feed, feed_id).current_upload.object_key
    store.put(key, make_gtfs_zip(route_id="HOSTED"))

    counts = tasks.load_feed(feed_id)

    assert counts["routes"] == 1
    assert static_feed(engine, feed_id).status == LoadStatus.success
    with Session(engine) as session:
        assert session.execute(select(GtfsRoute.route_id)).scalar_one() == "HOSTED"


def test_url_feed_still_downloads(engine, session_factory, store, monkeypatch):
    feed_id = make_feed(engine, hosted=False)
    seen = {}

    def fake_download(url, timeout, max_bytes):
        seen["url"] = url
        return make_gtfs_zip(route_id="FETCHED")

    monkeypatch.setattr(tasks, "download_gtfs_zip", fake_download)

    tasks.load_feed(feed_id)

    assert seen["url"] == "https://example.com/gtfs.zip"
    assert static_feed(engine, feed_id).status == LoadStatus.success


def test_hosted_feed_with_no_upload_fails_without_retrying(
    engine, session_factory, store
):
    feed_id = make_feed(engine, hosted=True, with_upload=False)

    with pytest.raises(ValueError, match="no current upload"):
        tasks.load_feed(feed_id)

    gsf = static_feed(engine, feed_id)
    assert gsf.status == LoadStatus.failed
    assert "no uploaded schedule" in gsf.error_message


def test_hosted_feed_whose_object_is_gone_fails_without_retrying(
    engine, session_factory, store
):
    feed_id = make_feed(engine, hosted=True)

    with pytest.raises(ObjectNotFound):
        tasks.load_feed(feed_id)

    gsf = static_feed(engine, feed_id)
    assert gsf.status == LoadStatus.failed
    assert "missing" in gsf.error_message


def _loaded(engine, feed_id: int, *, status: str, last_loaded_at, next_retry_at=None):
    with Session(engine) as session:
        gsf = GtfsStaticFeed(
            status=status, last_loaded_at=last_loaded_at, next_retry_at=next_retry_at
        )
        session.add(gsf)
        session.commit()
        session.get(Feed, feed_id).gtfs_static_feed_id = gsf.id
        session.commit()


def test_beat_skips_a_hosted_feed_that_loaded_fine(
    engine, session_factory, monkeypatch
):
    enqueued = []
    monkeypatch.setattr(tasks.load_feed, "delay", enqueued.append)
    stale = _now() - timedelta(days=7)

    hosted = make_feed(engine, hosted=True, feed_name="hosted-feed")
    url = make_feed(engine, hosted=False, feed_name="url-feed")
    _loaded(engine, hosted, status=LoadStatus.success, last_loaded_at=stale)
    _loaded(engine, url, status=LoadStatus.success, last_loaded_at=stale)

    assert tasks.ensure_all_feeds_scheduled() == 1
    assert enqueued == [url]


def test_beat_still_repairs_a_hosted_feed_that_failed(
    engine, session_factory, monkeypatch
):
    enqueued = []
    monkeypatch.setattr(tasks.load_feed, "delay", enqueued.append)

    hosted = make_feed(engine, hosted=True, feed_name="hosted-feed")
    _loaded(
        engine,
        hosted,
        status=LoadStatus.failed,
        last_loaded_at=_now() - timedelta(days=7),
        next_retry_at=_now() - timedelta(hours=1),
    )

    assert tasks.ensure_all_feeds_scheduled() == 1
    assert enqueued == [hosted]


def test_beat_still_picks_up_a_hosted_feed_that_never_loaded(
    engine, session_factory, monkeypatch
):
    enqueued = []
    monkeypatch.setattr(tasks.load_feed, "delay", enqueued.append)

    hosted = make_feed(engine, hosted=True, feed_name="hosted-feed")

    assert tasks.ensure_all_feeds_scheduled() == 1
    assert enqueued == [hosted]
