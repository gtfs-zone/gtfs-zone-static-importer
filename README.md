# schedule-foamer

Celery worker that downloads GTFS static feeds, parses them, and writes to PostgreSQL tables
managed by [redis-gtfs-rt-api](../redis-gtfs-rt-api).

## Quick start

```bash
cp .env.example .env
# Edit .env with your DATABASE_URL and Redis URLs
uv sync
uv run pre-commit install   # install git hooks (required once per clone)
uv run celery -A worker.celery_app worker -l info
```

## Development commands

```bash
# Install git hooks (required once per clone)
uv run pre-commit install

uv run ruff check src/          # lint
uv run ruff check --fix src/    # lint + autofix
```

## Docker

Built and run as part of `redis-gtfs-rt-api`'s docker-compose:

```bash
cd ../redis-gtfs-rt-api
docker compose up --build
```

## Tasks

| Task | Description |
|------|-------------|
| `worker.tasks.load_feed` | Download and parse a single GTFS feed by ID |
| `worker.tasks.refresh_all_feeds` | Enqueue `load_feed` for every feed (runs daily at 02:00 UTC) |
| `worker.tasks.ensure_all_feeds_scheduled` | Re-enqueue feeds with no status or failed status (runs every minute) |
