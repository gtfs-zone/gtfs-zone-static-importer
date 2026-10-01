from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": the .env also carries the S3_* keys gtfs-zone-db-models's
    # ObjectStoreSettings reads, which are not this model's to declare.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = ""
    celery_broker_url: str = "redis://localhost:6379/3"
    celery_result_backend: str = "redis://localhost:6379/4"
    # Where load-status events are published. rt-api subscribes on the same
    # URL and forwards to rt-manager; pub/sub ignores the db number, but the
    # two are pointed at one db anyway rather than relying on that.
    redis_url: str = "redis://localhost:6379/1"
    httpx_timeout: float = 60.0
    feed_refresh_interval_minutes: int = 1440  # 24 hours
    celery_worker_concurrency: int = 2
    celery_max_tasks_per_child: int = 10
    max_gtfs_zip_bytes: int = 31457280  # 30 MB
    # The object store a hosted feed is read from is configured by
    # gtfs_zone_db_models.object_store.ObjectStoreSettings, off the same .env:
    # S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION. Not mirrored
    # here, so rt-api and this worker cannot be pointed at different buckets by
    # accident.


settings = Settings()
