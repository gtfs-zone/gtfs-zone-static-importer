# AGENTS.md

Celery worker (with beat, no HTTP server) that downloads GTFS static feeds and
writes them to the PostgreSQL tables defined in gtfs-zone-db-models. A `v*` tag
publishes the image.

## Architecture

Tasks are in `src/gtfs_zone_static_importer/tasks.py` and listed in
[README.md](README.md); parsing is in `gtfs_loader.py`.

- **Sync only**: psycopg2, no asyncpg, no asyncio in tasks.
- **Session per task** via `get_session()`; never share a session across tasks.
- **Delete-then-insert** per `feed_id` in one transaction, not per-row upserts.
  `stop_times` uses SQLAlchemy Core bulk insert.
- A feed is `hosted` or `url` (`feed.is_hosted`). Hosted bytes come from
  `read_gtfs_object` in object storage and are never re-downloaded from
  `static_feed_url`; `url` feeds are downloaded fresh on every refresh.
- `arrival_time` and `departure_time` are TEXT (GTFS allows `25:30:00`). Rows
  with either null are filtered out during parse.
- Never run Alembic here; migrations live in gtfs-zone-db-models.

## Conventions

- **Commits**: Conventional Commits, enforced by the `commit-msg` hook. Never add
  Co-Authored-By trailers. Setup, release and `gtfs-zone-db-models` changes are
  in [CONTRIBUTING.md](CONTRIBUTING.md).
- **Logging**: module loggers are named `log`, never `logger`.
- **Plans**: write plans to `CURRENT_PLAN.md` at the repo root as a
  checklist (`- [ ]`), ticked off as work lands. It is neither tracked nor
  gitignored: never stage or commit it.
