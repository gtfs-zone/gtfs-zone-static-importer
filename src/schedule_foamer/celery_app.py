from celery import Celery
from celery.schedules import crontab

from schedule_foamer.settings import settings

celery_app = Celery(
    "schedule_foamer",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["schedule_foamer.tasks"],  # required for task discovery
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    ONCE={
        "backend": "celery_singleton.backends.RedisBackend",
        "settings": {"url": settings.celery_broker_url},
        "default_timeout": 60 * 60,  # 1 hour — longer than worst-case task duration
    },
    worker_concurrency=settings.celery_worker_concurrency,
    worker_max_tasks_per_child=settings.celery_max_tasks_per_child,
    beat_schedule={
        "startup-ensure-scheduled": {
            "task": "schedule_foamer.tasks.ensure_all_feeds_scheduled",
            "schedule": crontab(),  # every minute, idempotent
        },
    },
)
