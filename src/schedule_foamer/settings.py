from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = ""
    celery_broker_url: str = "redis://localhost:6379/3"
    celery_result_backend: str = "redis://localhost:6379/4"
    httpx_timeout: float = 60.0
    feed_refresh_interval_minutes: int = 1440  # 24 hours
    celery_worker_concurrency: int = 2
    celery_max_tasks_per_child: int = 10
    max_gtfs_zip_bytes: int = 31457280 # 30 MB


settings = Settings()
