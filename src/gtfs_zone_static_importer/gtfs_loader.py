import csv
import io
import zipfile
from collections.abc import Iterable, Iterator
from typing import Any

import httpx
from gtfs_zone_db_models.models import GtfsRoute, GtfsStop, GtfsStopTime, GtfsTrip
from gtfs_zone_db_models.object_store import get_object_store
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

Row = dict[str, Any]
_CHUNK = 1000


def download_gtfs_zip(url: str, timeout: float, max_bytes: int) -> bytes:
    with (
        httpx.Client(timeout=timeout, follow_redirects=True) as client,
        client.stream("GET", url) as r,
    ):
        r.raise_for_status()
        length_str = r.headers.get("content-length")
        if length_str is not None and int(length_str) > max_bytes:
            raise ValueError(
                f"GTFS zip Content-Length {length_str} exceeds limit {max_bytes}"
            )
        chunks = []
        received = 0
        for chunk in r.iter_bytes():
            received += len(chunk)
            if received > max_bytes:
                raise ValueError(
                    f"GTFS zip body exceeded limit {max_bytes} during download"
                )
            chunks.append(chunk)
        return b"".join(chunks)


def read_gtfs_object(key: str, max_bytes: int) -> bytes:
    """Read a hosted feed's zip out of object storage.

    The store client is built here rather than at import so a worker that
    starts before the store is reachable does not die on the way up.

    The cap is applied again even though the upload endpoint already enforced
    it: an object can predate a lowered cap, and the parse after this holds the
    whole thing in memory either way. `stat` first, so an oversized object is
    refused without transferring it.
    """
    store = get_object_store()
    size = store.stat(key).size_bytes
    if size > max_bytes:
        raise ValueError(f"GTFS object {key!r} is {size} bytes, over limit {max_bytes}")
    body = store.get(key)
    if len(body) > max_bytes:
        raise ValueError(
            f"GTFS object {key!r} body exceeded limit {max_bytes}"
            f" after stat said {size}"
        )
    return body


def _iter_csv(zf: zipfile.ZipFile, name: str) -> Iterator[Row]:
    try:
        with zf.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
    except KeyError:
        return


def _parse_agency_timezone(rows: Iterable[Row]) -> str | None:
    for r in rows:
        tz = r.get("agency_timezone", "").strip()
        if tz:
            return tz
    return None


def _parse_stops(rows: Iterable[Row], gtfs_static_feed_id: int) -> Iterator[Row]:
    for r in rows:
        lat, lon = r.get("stop_lat", "").strip(), r.get("stop_lon", "").strip()
        if not lat or not lon:
            continue
        yield {
            "gtfs_static_feed_id": gtfs_static_feed_id,
            "stop_id": r["stop_id"].strip(),
            "stop_name": r.get("stop_name", "").strip(),
            "stop_lat": float(lat),
            "stop_lon": float(lon),
            "stop_code": r.get("stop_code", "").strip() or None,
            "stop_desc": r.get("stop_desc", "").strip() or None,
        }


def _parse_routes(rows: Iterable[Row], gtfs_static_feed_id: int) -> Iterator[Row]:
    for r in rows:
        yield {
            "gtfs_static_feed_id": gtfs_static_feed_id,
            "route_id": r["route_id"].strip(),
            "agency_id": r.get("agency_id", "").strip() or None,
            "route_short_name": r.get("route_short_name", "").strip(),
            "route_long_name": r.get("route_long_name", "").strip(),
            "route_type": int(r.get("route_type", 0)),
        }


def _parse_trips(rows: Iterable[Row], gtfs_static_feed_id: int) -> Iterator[Row]:
    for r in rows:
        yield {
            "gtfs_static_feed_id": gtfs_static_feed_id,
            "trip_id": r["trip_id"].strip(),
            "route_id": r["route_id"].strip(),
            "service_id": r["service_id"].strip(),
            "trip_headsign": r.get("trip_headsign", "").strip() or None,
            "direction_id": int(r["direction_id"])
            if r.get("direction_id", "").strip()
            else None,
        }


def _parse_stop_times(rows: Iterable[Row], gtfs_static_feed_id: int) -> Iterator[Row]:
    for r in rows:
        arr = r.get("arrival_time", "").strip()
        dep = r.get("departure_time", "").strip()
        if not arr or not dep:  # NEVER store null per project rules
            continue
        yield {
            "gtfs_static_feed_id": gtfs_static_feed_id,
            "trip_id": r["trip_id"].strip(),
            "stop_id": r["stop_id"].strip(),
            "arrival_time": arr,
            "departure_time": dep,
            "stop_sequence": int(r["stop_sequence"]),
        }


def _bulk_insert(
    session: Session, model: type, rows: Iterable[Row], chunk_size: int = _CHUNK
) -> int:
    stmt = insert(model.__table__)
    chunk, count = [], 0
    for row in rows:
        chunk.append(row)
        if len(chunk) >= chunk_size:
            session.execute(stmt, chunk)
            count += len(chunk)
            chunk = []
    if chunk:
        session.execute(stmt, chunk)
        count += len(chunk)
    return count


def load_feed_data(
    session: Session, gtfs_static_feed_id: int, zip_bytes: bytes
) -> dict:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        timezone = _parse_agency_timezone(_iter_csv(zf, "agency.txt"))

        # Delete old data (FK order) before streaming new data in
        for model in (GtfsStopTime, GtfsTrip, GtfsRoute, GtfsStop):
            session.execute(
                delete(model).where(model.gtfs_static_feed_id == gtfs_static_feed_id)
            )

        n_stops = _bulk_insert(
            session,
            GtfsStop,
            _parse_stops(_iter_csv(zf, "stops.txt"), gtfs_static_feed_id),
        )
        n_routes = _bulk_insert(
            session,
            GtfsRoute,
            _parse_routes(_iter_csv(zf, "routes.txt"), gtfs_static_feed_id),
        )
        n_trips = _bulk_insert(
            session,
            GtfsTrip,
            _parse_trips(_iter_csv(zf, "trips.txt"), gtfs_static_feed_id),
        )
        n_stoptimes = _bulk_insert(
            session,
            GtfsStopTime,
            _parse_stop_times(_iter_csv(zf, "stop_times.txt"), gtfs_static_feed_id),
        )

    return {
        "stops": n_stops,
        "routes": n_routes,
        "trips": n_trips,
        "stoptimes": n_stoptimes,
        "timezone": timezone,
    }
