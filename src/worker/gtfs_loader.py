import csv
import io
import zipfile

import httpx
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from railroad_club.models import GtfsRoute, GtfsStop, GtfsStopTime, GtfsTrip

_CHUNK = 1000


def download_gtfs_zip(url: str, timeout: float, max_bytes: int) -> bytes:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client, client.stream("GET", url) as r:
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


def _iter_csv(zf: zipfile.ZipFile, name: str):
    try:
        with zf.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
    except KeyError:
        return


def _parse_agency_timezone(rows) -> str | None:
    for r in rows:
        tz = r.get("agency_timezone", "").strip()
        if tz:
            return tz
    return None


def _parse_stops(rows, gtfs_static_feed_id):
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


def _parse_routes(rows, gtfs_static_feed_id):
    for r in rows:
        yield {
            "gtfs_static_feed_id": gtfs_static_feed_id,
            "route_id": r["route_id"].strip(),
            "agency_id": r.get("agency_id", "").strip() or None,
            "route_short_name": r.get("route_short_name", "").strip(),
            "route_long_name": r.get("route_long_name", "").strip(),
            "route_type": int(r.get("route_type", 0)),
        }


def _parse_trips(rows, gtfs_static_feed_id):
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


def _parse_stop_times(rows, gtfs_static_feed_id):
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


def _bulk_insert(session: Session, model, rows, chunk_size: int = _CHUNK) -> int:
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


def load_feed_data(session: Session, gtfs_static_feed_id: int, zip_bytes: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        timezone = _parse_agency_timezone(_iter_csv(zf, "agency.txt"))

        # Delete old data (FK order) before streaming new data in
        session.execute(delete(GtfsStopTime).where(GtfsStopTime.gtfs_static_feed_id == gtfs_static_feed_id))
        session.execute(delete(GtfsTrip).where(GtfsTrip.gtfs_static_feed_id == gtfs_static_feed_id))
        session.execute(delete(GtfsRoute).where(GtfsRoute.gtfs_static_feed_id == gtfs_static_feed_id))
        session.execute(delete(GtfsStop).where(GtfsStop.gtfs_static_feed_id == gtfs_static_feed_id))

        n_stops = _bulk_insert(session, GtfsStop, _parse_stops(_iter_csv(zf, "stops.txt"), gtfs_static_feed_id))
        n_routes = _bulk_insert(session, GtfsRoute, _parse_routes(_iter_csv(zf, "routes.txt"), gtfs_static_feed_id))
        n_trips = _bulk_insert(session, GtfsTrip, _parse_trips(_iter_csv(zf, "trips.txt"), gtfs_static_feed_id))
        n_stoptimes = _bulk_insert(session, GtfsStopTime, _parse_stop_times(_iter_csv(zf, "stop_times.txt"), gtfs_static_feed_id))

    return {"stops": n_stops, "routes": n_routes, "trips": n_trips, "stoptimes": n_stoptimes, "timezone": timezone}
