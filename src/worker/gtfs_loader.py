import csv
import io
import zipfile

import httpx
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from worker.models import GtfsRoute, GtfsStop, GtfsStopTime, GtfsTrip

_CHUNK = 1000


def download_gtfs_zip(url: str, timeout: float) -> bytes:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    try:
        with zf.open(name) as f:
            return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
    except KeyError:
        return []


def _parse_stops(rows, feed_id) -> list[dict]:
    out = []
    for r in rows:
        lat, lon = r.get("stop_lat", "").strip(), r.get("stop_lon", "").strip()
        if not lat or not lon:
            continue
        out.append(
            {
                "feed_id": feed_id,
                "stop_id": r["stop_id"].strip(),
                "stop_name": r.get("stop_name", "").strip(),
                "stop_lat": float(lat),
                "stop_lon": float(lon),
                "stop_code": r.get("stop_code", "").strip() or None,
                "stop_desc": r.get("stop_desc", "").strip() or None,
            }
        )
    return out


def _parse_routes(rows, feed_id) -> list[dict]:
    return [
        {
            "feed_id": feed_id,
            "route_id": r["route_id"].strip(),
            "agency_id": r.get("agency_id", "").strip() or None,
            "route_short_name": r.get("route_short_name", "").strip(),
            "route_long_name": r.get("route_long_name", "").strip(),
            "route_type": int(r.get("route_type", 0)),
        }
        for r in rows
    ]


def _parse_trips(rows, feed_id) -> list[dict]:
    return [
        {
            "feed_id": feed_id,
            "trip_id": r["trip_id"].strip(),
            "route_id": r["route_id"].strip(),
            "service_id": r["service_id"].strip(),
            "trip_headsign": r.get("trip_headsign", "").strip() or None,
            "direction_id": int(r["direction_id"])
            if r.get("direction_id", "").strip()
            else None,
        }
        for r in rows
    ]


def _parse_stop_times(rows, feed_id) -> list[dict]:
    out = []
    for r in rows:
        arr = r.get("arrival_time", "").strip()
        dep = r.get("departure_time", "").strip()
        if not arr or not dep:  # NEVER store null per project rules
            continue
        out.append(
            {
                "feed_id": feed_id,
                "trip_id": r["trip_id"].strip(),
                "stop_id": r["stop_id"].strip(),
                "arrival_time": arr,
                "departure_time": dep,
                "stop_sequence": int(r["stop_sequence"]),
            }
        )
    return out


def _bulk_insert(session: Session, model, rows: list[dict]) -> None:
    if not rows:
        return
    stmt = insert(model.__table__)
    for i in range(0, len(rows), _CHUNK):
        session.execute(stmt, rows[i : i + _CHUNK])


def load_feed_data(session: Session, feed_id: int, zip_bytes: bytes) -> dict[str, int]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        stops = _parse_stops(_read_csv(zf, "stops.txt"), feed_id)
        routes = _parse_routes(_read_csv(zf, "routes.txt"), feed_id)
        trips = _parse_trips(_read_csv(zf, "trips.txt"), feed_id)
        stoptimes = _parse_stop_times(_read_csv(zf, "stop_times.txt"), feed_id)

    # Delete child tables first (FK order)
    session.execute(delete(GtfsStopTime).where(GtfsStopTime.feed_id == feed_id))
    session.execute(delete(GtfsTrip).where(GtfsTrip.feed_id == feed_id))
    session.execute(delete(GtfsRoute).where(GtfsRoute.feed_id == feed_id))
    session.execute(delete(GtfsStop).where(GtfsStop.feed_id == feed_id))

    _bulk_insert(session, GtfsStop, stops)
    _bulk_insert(session, GtfsRoute, routes)
    _bulk_insert(session, GtfsTrip, trips)
    _bulk_insert(session, GtfsStopTime, stoptimes)

    return {"stops": len(stops), "routes": len(routes), "trips": len(trips)}
