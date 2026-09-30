# schedule-foamer

Celery worker that downloads GTFS static feeds, parses them, and writes to PostgreSQL tables
defined in [railroad-club](https://github.com/gtfs-zone/railroad-club).

## Quick start

```bash
cp .env.example .env
# Edit .env with your DATABASE_URL and Redis URLs
uv sync
uv run pre-commit install   # install git hooks (required once per clone)
uv run celery -A schedule_foamer.celery_app worker -l info
uv run celery -A schedule_foamer.celery_app beat -l info   # periodic scheduling, separate process
```

## Development commands

```bash
# Install git hooks (required once per clone)
uv run pre-commit install

uv run ruff check src/          # lint
uv run ruff check --fix src/    # lint + autofix
```

## Docker

Built and run as part of [music-student](https://github.com/gtfs-zone/music-student)'s docker-compose:

```bash
cd ../music-student
docker compose up --build
```

## Tasks

| Task | Description |
|------|-------------|
| `schedule_foamer.tasks.load_feed` | Download and parse a single GTFS feed by ID |
| `schedule_foamer.tasks.ensure_all_feeds_scheduled` | Enqueue `load_feed` for feeds never loaded, failed, stuck, or (url feeds only) last loaded over 24h ago (runs every minute) |
