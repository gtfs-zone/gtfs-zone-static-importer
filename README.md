# gtfs-zone-static-importer

[![CI](https://img.shields.io/github/actions/workflow/status/gtfs-zone/gtfs-zone-static-importer/check.yml?branch=main&label=CI)](https://github.com/gtfs-zone/gtfs-zone-static-importer/actions/workflows/check.yml?query=branch%3Amain) [![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue)](LICENSE.txt) [![Container image](https://img.shields.io/badge/image-ghcr.io-blue?logo=docker&logoColor=white)](https://github.com/gtfs-zone/gtfs-zone-static-importer/pkgs/container/gtfs-zone-static-importer)

Celery worker that downloads GTFS static feeds, parses them, and writes to PostgreSQL tables
defined in [gtfs-zone-db-models](https://github.com/gtfs-zone/gtfs-zone-db-models).

## Quick start

```bash
cp .env.example .env
# Edit .env with your DATABASE_URL and Redis URLs
uv sync
uv run pre-commit install   # install git hooks (required once per clone)
uv run celery -A gtfs_zone_static_importer.celery_app worker -l info
uv run celery -A gtfs_zone_static_importer.celery_app beat -l info   # periodic scheduling, separate process
```

## Development commands

```bash
# Install git hooks (required once per clone)
uv run pre-commit install

uv run ruff check src/          # lint
uv run ruff check --fix src/    # lint + autofix
```

## Docker

Built and run as part of [dev-stack](https://github.com/gtfs-zone/gtfs-zone-dev-stack)'s docker-compose:

```bash
cd ../gtfs-zone-dev-stack
docker compose up --build
```

## Tasks

| Task | Description |
|------|-------------|
| `gtfs_zone_static_importer.tasks.load_feed` | Download and parse a single GTFS feed by ID |
| `gtfs_zone_static_importer.tasks.ensure_all_feeds_scheduled` | Enqueue `load_feed` for feeds never loaded, failed, stuck, or (url feeds only) last loaded over 24h ago (runs every minute) |
