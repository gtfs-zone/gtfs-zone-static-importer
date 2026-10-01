# gtfs-zone-static-importer

Celery worker that downloads GTFS static feeds and writes parsed data to PostgreSQL tables
owned by `rt-api`.

## Architecture

- **Celery worker** with beat scheduler, no HTTP server
- **Sync only** (psycopg2-binary, no asyncpg, no asyncio in tasks)
- **Session-per-task** via `get_session()` context manager; never share sessions across tasks
- **Delete-then-insert** per feed_id in a single transaction (not upsert per row)
- **SQLAlchemy Core bulk insert** for stop_times performance

## The two source kinds

A `Feed`'s `source_kind` (`gtfs_zone_db_models.models.gtfs_upload.FeedSourceKind`)
is `hosted` or `url`. `tasks.py` branches on `feed.is_hosted`: a hosted feed's
bytes come from `read_gtfs_object` against object storage (Garage), the zip
someone uploaded through rt-api; a `url` feed is downloaded fresh with
`download_gtfs_zip` on every refresh, as it always has been. Hosted feeds are
never re-downloaded from `Feed.static_feed_url`.

## Important Rules

- Never add Co-Authored-By: Claude ... trailers to commit messages

## Key rules

- Never store `GtfsStopTime` with null `arrival_time` or `departure_time`; filter rows during parse
- `arrival_time` and `departure_time` are stored as TEXT (GTFS allows values like `25:30:00` for overnight trips)
- Never run Alembic here; schema migrations live in `rt-api`
- Use psycopg2 (sync) only, no asyncpg
- Module loggers are named `log`, never `logger`: `log = logging.getLogger(__name__)`

## Package management

- `uv` for all package management
- Run `uv sync` to install dependencies
- Run `uv run ruff check src/` before committing

## Pre-commit hooks

Commitizen enforces [Conventional Commits](https://www.conventionalcommits.org/) on every commit message.

```bash
# Install hooks (required once per clone)
uv run pre-commit install
```

## Running locally

```bash
uv sync
uv run celery -A gtfs_zone_static_importer.celery_app worker -l info
# In a separate terminal for beat:
uv run celery -A gtfs_zone_static_importer.celery_app beat -l info
```

## Module structure

The package is `gtfs_zone_static_importer` (installed via hatchling from `src/gtfs_zone_static_importer`).
