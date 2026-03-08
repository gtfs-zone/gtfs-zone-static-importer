from celery import Celery
from celery.schedules import crontab

from worker.settings import settings

celery_app = Celery(
    "worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["worker.tasks"],  # required for task discovery
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "startup-ensure-scheduled": {
            "task": "worker.tasks.ensure_all_feeds_scheduled",
            "schedule": crontab(),  # every minute, idempotent
        },
    },
)
