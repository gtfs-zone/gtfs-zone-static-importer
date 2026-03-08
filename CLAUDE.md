# schedule-foamer

Celery worker that downloads GTFS static feeds and writes parsed data to PostgreSQL tables
owned by `redis-gtfs-rt-api`.

## Architecture

- **Celery worker** with beat scheduler — no HTTP server
- **Sync only** — psycopg2-binary, no asyncpg, no asyncio in tasks
- **Session-per-task** via `get_session()` context manager — never share sessions across tasks
- **Delete-then-insert** per feed_id in a single transaction (not upsert per row)
- **SQLAlchemy Core bulk insert** for stop_times performance

## Key rules

- Never store `GtfsStopTime` with null `arrival_time` or `departure_time` — filter rows during parse
- `arrival_time` and `departure_time` are stored as TEXT (GTFS allows values like `25:30:00` for overnight trips)
- Never run Alembic here — schema migrations live in `redis-gtfs-rt-api`
- Use psycopg2 (sync) only — no asyncpg

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
uv run celery -A worker.celery_app worker -l info
# In a separate terminal for beat:
uv run celery -A worker.celery_app beat -l info
```

## Module structure

The package is `worker` (installed via hatchling from `src/worker`), matching
`celery -A worker.celery_app` used in the sibling docker-compose.
