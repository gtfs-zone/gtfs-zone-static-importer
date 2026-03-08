import traceback
from datetime import datetime, timedelta, timezone

from celery.utils.log import get_task_logger
from sqlalchemy import select

from worker.celery_app import celery_app
from worker.database import get_session
from worker.gtfs_loader import download_gtfs_zip, load_feed_data
from worker.models import Feed, GtfsStaticFeed, LoadStatus
from worker.settings import settings

logger = get_task_logger(__name__)


@celery_app.task(bind=True, name="worker.tasks.load_feed", max_retries=3)
def load_feed(self, feed_id: int) -> dict:
    logger.info("load_feed feed_id=%s", feed_id)

    # 1. Get or create GtfsStaticFeed, set status=running
    with get_session() as session:
        feed = session.get(Feed, feed_id)
        if feed is None:
            raise ValueError(f"Feed {feed_id} not found")
        url = feed.static_feed_url
        if feed.gtfs_static_feed_id:
            gsf = session.get(GtfsStaticFeed, feed.gtfs_static_feed_id)
            gsf.status = LoadStatus.running
            gsf.error_message = None
        else:
            gsf = GtfsStaticFeed(status=LoadStatus.running)
            session.add(gsf)
            session.flush()
            feed.gtfs_static_feed_id = gsf.id
        session.commit()
        gsf_id = gsf.id

    # 2. Download zip (outside session)
    try:
        zip_bytes = download_gtfs_zip(url, timeout=settings.httpx_timeout)
    except Exception as exc:
        with get_session() as session:
            gsf = session.get(GtfsStaticFeed, gsf_id)
            gsf.status = LoadStatus.failed
            gsf.error_message = f"Download failed: {exc}"
            session.commit()
        raise self.retry(exc=exc, countdown=60)

    # 3. Load data, update GtfsStaticFeed
    try:
        with get_session() as session:
            counts = load_feed_data(session, gsf_id, zip_bytes)
            gsf = session.get(GtfsStaticFeed, gsf_id)
            gsf.timezone = counts["timezone"]
            gsf.status = LoadStatus.success
            gsf.last_loaded_at = datetime.now(timezone.utc)
            session.commit()
        logger.info("load_feed feed_id=%s done: %s", feed_id, counts)
        return counts
    except Exception as exc:
        with get_session() as session:
            gsf = session.get(GtfsStaticFeed, gsf_id)
            gsf.status = LoadStatus.failed
            gsf.error_message = traceback.format_exc()[:2000]
            gsf.last_loaded_at = datetime.now(timezone.utc)
            session.commit()
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="worker.tasks.ensure_all_feeds_scheduled")
def ensure_all_feeds_scheduled() -> int:
    """Re-enqueue feeds with no gtfs_static_feed, failed status, or last loaded >24h ago."""
    due_before = datetime.now(timezone.utc) - timedelta(minutes=settings.feed_refresh_interval_minutes)
    with get_session() as session:
        rows = session.execute(
            select(Feed.id, GtfsStaticFeed.status)
            .outerjoin(GtfsStaticFeed, Feed.gtfs_static_feed_id == GtfsStaticFeed.id)
            .where(
                Feed.gtfs_static_feed_id.is_(None)
                | (GtfsStaticFeed.status == LoadStatus.failed)
                | (
                    (GtfsStaticFeed.status != LoadStatus.running)
                    & (GtfsStaticFeed.last_loaded_at < due_before)
                )
            )
        ).all()
    for fid, _ in rows:
        load_feed.delay(fid)
    return len(rows)
