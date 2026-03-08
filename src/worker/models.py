from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlmodel import Field, SQLModel


class LoadStatus(StrEnum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class GtfsStaticFeed(SQLModel, table=True):
    __tablename__ = "gtfs_static_feed"

    id: Optional[int] = Field(default=None, primary_key=True)
    timezone: Optional[str] = None
    status: str = Field(default=LoadStatus.pending)
    error_message: Optional[str] = None
    last_loaded_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None


class Feed(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    feed_name: str
    static_feed_url: str
    owner_id: int
    gtfs_static_feed_id: Optional[int] = None


class GtfsStop(SQLModel, table=True):
    __tablename__ = "gtfs_stop"
    id: Optional[int] = Field(default=None, primary_key=True)
    gtfs_static_feed_id: int = Field(foreign_key="gtfs_static_feed.id")
    stop_id: str
    stop_name: str
    stop_lat: float
    stop_lon: float
    stop_code: Optional[str] = None
    stop_desc: Optional[str] = None


class GtfsRoute(SQLModel, table=True):
    __tablename__ = "gtfs_route"
    id: Optional[int] = Field(default=None, primary_key=True)
    gtfs_static_feed_id: int = Field(foreign_key="gtfs_static_feed.id")
    route_id: str
    agency_id: Optional[str] = None
    route_short_name: str
    route_long_name: str
    route_type: int


class GtfsTrip(SQLModel, table=True):
    __tablename__ = "gtfs_trip"
    id: Optional[int] = Field(default=None, primary_key=True)
    gtfs_static_feed_id: int = Field(foreign_key="gtfs_static_feed.id")
    trip_id: str
    route_id: str
    service_id: str
    trip_headsign: Optional[str] = None
    direction_id: Optional[int] = None


class GtfsStopTime(SQLModel, table=True):
    __tablename__ = "gtfs_stop_time"
    id: Optional[int] = Field(default=None, primary_key=True)
    gtfs_static_feed_id: int = Field(foreign_key="gtfs_static_feed.id")
    trip_id: str
    stop_id: str
    arrival_time: str  # NEVER NULL — filtered during parse; TEXT because GTFS allows 25:30:00
    departure_time: str  # NEVER NULL — filtered during parse; TEXT because GTFS allows 25:30:00
    stop_sequence: int
