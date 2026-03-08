import traceback
from datetime import datetime, timedelta, timezone

from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from worker.celery_app import celery_app
from worker.database import get_session
from worker.gtfs_loader import download_gtfs_zip, load_feed_data
from worker.models import Feed, FeedLoadStatus, LoadStatus
from worker.settings import settings

logger = get_task_logger(__name__)


def _upsert_status(session, feed_id: int, **kwargs) -> None:
    stmt = (
        pg_insert(FeedLoadStatus)
        .values(feed_id=feed_id, **kwargs)
        .on_conflict_do_update(index_elements=["feed_id"], set_=kwargs)
    )
    session.execute(stmt)
    session.commit()


@celery_app.task(bind=True, name="worker.tasks.load_feed", max_retries=3)
def load_feed(self, feed_id: int) -> dict:
    logger.info("load_feed feed_id=%s", feed_id)

    with get_session() as session:
        feed = session.get(Feed, feed_id)
        if feed is None:
            raise ValueError(f"Feed {feed_id} not found")
        url = feed.static_feed_url
        _upsert_status(session, feed_id, status=LoadStatus.running, error_message=None)

    # Download outside session to avoid long-held connections
    try:
        zip_bytes = download_gtfs_zip(url, timeout=settings.httpx_timeout)
    except Exception as exc:
        with get_session() as session:
            _upsert_status(
                session,
                feed_id,
                status=LoadStatus.failed,
                error_message=f"Download failed: {exc}",
                last_loaded_at=datetime.now(timezone.utc),
            )
        raise self.retry(exc=exc, countdown=60)

    try:
        with get_session() as session:
            counts = load_feed_data(session, feed_id, zip_bytes)
            session.commit()
            _upsert_status(
                session,
                feed_id,
                status=LoadStatus.success,
                last_loaded_at=datetime.now(timezone.utc),
                stop_count=counts["stops"],
                route_count=counts["routes"],
                trip_count=counts["trips"],
                error_message=None,
            )
        logger.info("load_feed feed_id=%s done: %s", feed_id, counts)
        return counts
    except Exception as exc:
        with get_session() as session:
            _upsert_status(
                session,
                feed_id,
                status=LoadStatus.failed,
                error_message=traceback.format_exc()[:2000],
                last_loaded_at=datetime.now(timezone.utc),
            )
        raise self.retry(exc=exc, countdown=60)



@celery_app.task(name="worker.tasks.ensure_all_feeds_scheduled")
def ensure_all_feeds_scheduled() -> int:
    """Re-enqueue feeds with no load status, failed status, or last loaded >24h ago."""
    due_before = datetime.now(timezone.utc) - timedelta(minutes=settings.feed_refresh_interval_minutes)
    with get_session() as session:
        rows = session.execute(
            select(Feed.id, FeedLoadStatus.status)
            .outerjoin(FeedLoadStatus, Feed.id == FeedLoadStatus.feed_id)
            .where(
                FeedLoadStatus.feed_id.is_(None)
                | (FeedLoadStatus.status == LoadStatus.failed)
                | (
                    (FeedLoadStatus.status != LoadStatus.running)
                    & (FeedLoadStatus.last_loaded_at < due_before)
                )
            )
        ).all()
    for fid, _ in rows:
        load_feed.delay(fid)
    return len(rows)
