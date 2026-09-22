import random
import traceback
from datetime import UTC, datetime, timedelta

from celery import Task
from celery.utils.log import get_task_logger
from celery_singleton import Singleton
from railroad_club.models import Feed, GtfsStaticFeed, LoadStatus
from railroad_club.models.gtfs_upload import FeedSourceKind
from railroad_club.object_store import ObjectNotFound
from sqlalchemy import select, update

from schedule_foamer.celery_app import celery_app
from schedule_foamer.database import get_session
from schedule_foamer.events import publish_load
from schedule_foamer.gtfs_loader import (
    download_gtfs_zip,
    load_feed_data,
    read_gtfs_object,
)
from schedule_foamer.settings import settings

log = get_task_logger(__name__)


def _fail_load(
    feed_id: int, gsf_id: int, message: str, *, permanent: bool = False
) -> None:
    """Record a failed load and push it, before the task raises.

    ``permanent`` only says the Celery retry is pointless; the row still gets
    the ordinary 24h ``next_retry_at`` so the beat sweep picks it up once a day
    rather than on every pass.
    """
    with get_session() as session:
        gsf = session.get(GtfsStaticFeed, gsf_id)
        gsf.status = LoadStatus.failed
        gsf.error_message = message
        gsf.next_retry_at = datetime.now(UTC) + timedelta(hours=24)
        session.commit()
        publish_load(feed_id, gsf)
    if permanent:
        log.warning("load_feed feed_id=%s permanent failure: %s", feed_id, message)


@celery_app.task(
    bind=True,
    name="schedule_foamer.tasks.load_feed",
    base=Singleton,
    max_retries=3,
    raise_on_duplicate=False,
    unique_on=["feed_id"],
)
def load_feed(self: Task, feed_id: int) -> dict:
    log.info("load_feed feed_id=%s", feed_id)

    # 1. Get or create GtfsStaticFeed, set status=running
    with get_session() as session:
        feed = session.get(Feed, feed_id)
        if feed is None:
            raise ValueError(f"Feed {feed_id} not found")
        # Read the source while the feed is still attached. Steps 2 and 3 run
        # outside the session, so what they need has to come out as values.
        hosted = feed.is_hosted
        url = feed.static_feed_url
        object_key = feed.current_upload.object_key if feed.current_upload else None
        if feed.gtfs_static_feed_id:
            result = session.execute(
                update(GtfsStaticFeed)
                .where(
                    GtfsStaticFeed.id == feed.gtfs_static_feed_id,
                    GtfsStaticFeed.status != LoadStatus.running,
                )
                .values(
                    status=LoadStatus.running,
                    started_at=datetime.now(UTC),
                    next_retry_at=None,
                    error_message=None,
                )
                .returning(GtfsStaticFeed.id)
            )
            if result.fetchone() is None:
                log.info("load_feed feed_id=%s already running, skipping", feed_id)
                return {"skipped": True}
            gsf_id = feed.gtfs_static_feed_id
        else:
            gsf = GtfsStaticFeed(status=LoadStatus.running)
            session.add(gsf)
            session.flush()
            feed.gtfs_static_feed_id = gsf.id
            gsf.started_at = datetime.now(UTC)
            gsf.next_retry_at = None
            gsf_id = gsf.id
        session.commit()
        # After the commit, and re-read rather than reported from the local
        # variables: what is pushed has to be what a GET of the feed would say.
        publish_load(feed_id, session.get(GtfsStaticFeed, gsf_id))

    # 2. Get the zip bytes (outside session). Hosted feeds read the object
    # schedule-foamer's uploader wrote; url feeds download as they always have.
    if hosted and object_key is None:
        _fail_load(
            feed_id, gsf_id, "Hosted feed has no uploaded schedule", permanent=True
        )
        raise ValueError(f"Feed {feed_id} is hosted with no current upload")

    try:
        if hosted:
            zip_bytes = read_gtfs_object(
                object_key, max_bytes=settings.max_gtfs_zip_bytes
            )
        else:
            zip_bytes = download_gtfs_zip(
                url,
                timeout=settings.httpx_timeout,
                max_bytes=settings.max_gtfs_zip_bytes,
            )
    except ObjectNotFound as exc:
        # The row points at a key the store does not have. Retrying reads the
        # same missing key, so this waits for somebody to upload again.
        _fail_load(
            feed_id, gsf_id, f"Stored schedule is missing: {exc}", permanent=True
        )
        raise
    except Exception as exc:
        _fail_load(feed_id, gsf_id, f"Download failed: {exc}")
        raise self.retry(exc=exc, countdown=60 + random.uniform(0, 30)) from exc

    # 3. Load data, update GtfsStaticFeed
    try:
        with get_session() as session:
            counts = load_feed_data(session, gsf_id, zip_bytes)
            gsf = session.get(GtfsStaticFeed, gsf_id)
            gsf.timezone = counts["timezone"]
            gsf.status = LoadStatus.success
            gsf.last_loaded_at = datetime.now(UTC)
            session.commit()
            publish_load(feed_id, gsf)
        log.info("load_feed feed_id=%s done: %s", feed_id, counts)
        return counts
    except Exception as exc:
        with get_session() as session:
            gsf = session.get(GtfsStaticFeed, gsf_id)
            gsf.status = LoadStatus.failed
            gsf.error_message = traceback.format_exc()[:2000]
            gsf.last_loaded_at = datetime.now(UTC)
            gsf.next_retry_at = datetime.now(UTC) + timedelta(hours=24)
            session.commit()
            publish_load(feed_id, gsf)
        raise self.retry(exc=exc, countdown=60 + random.uniform(0, 30)) from exc


@celery_app.task(name="schedule_foamer.tasks.ensure_all_feeds_scheduled")
def ensure_all_feeds_scheduled() -> int:
    """Re-enqueue feeds unloaded, failed, or last loaded over 24h ago.

    The timed refresh is for url feeds alone. A hosted feed's zip only changes
    when somebody uploads one, and that upload enqueues the load itself, so
    re-reading the same object every 24h would be work with no possible result.
    A hosted feed that has never loaded, failed, or is stuck still comes
    through: those are repairs, not refreshes.
    """
    due_before = datetime.now(UTC) - timedelta(
        minutes=settings.feed_refresh_interval_minutes
    )
    stuck_threshold = datetime.now(UTC) - timedelta(minutes=5)
    with get_session() as session:
        rows = session.execute(
            select(Feed.id, GtfsStaticFeed.status)
            .outerjoin(GtfsStaticFeed, Feed.gtfs_static_feed_id == GtfsStaticFeed.id)
            .where(
                Feed.gtfs_static_feed_id.is_(None)
                | (
                    (GtfsStaticFeed.status == LoadStatus.failed)
                    & (
                        GtfsStaticFeed.next_retry_at.is_(None)
                        | (GtfsStaticFeed.next_retry_at <= datetime.now(UTC))
                    )
                )
                | (
                    (GtfsStaticFeed.status == LoadStatus.running)
                    & (GtfsStaticFeed.started_at < stuck_threshold)
                )
                | (
                    (GtfsStaticFeed.status == LoadStatus.success)
                    & (GtfsStaticFeed.last_loaded_at < due_before)
                    & (Feed.source_kind != FeedSourceKind.hosted)
                )
            )
        ).all()
    for fid, _ in rows:
        load_feed.delay(fid)
    return len(rows)
