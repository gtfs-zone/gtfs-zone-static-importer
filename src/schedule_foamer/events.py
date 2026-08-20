"""Publishing a feed's load status to the channel yard-master listens on.

The channel name and the payload shape are railroad-club's, so this repo and
cafe-car cannot drift apart on either. All that lives here is the connection
and the rule that a publish never fails a load.

That rule is the same one ``request_feed_load`` keeps on the other side: the
status is already committed, and a Redis that is down must not turn a finished
download into a retried task. A client that misses a push still gets the
current state on its next connect, because the SSE endpoint sends that first.

The client is built lazily rather than at import, so each prefork worker child
opens its own rather than inheriting a socket from the parent.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

from railroad_club.feed_events import feed_channel, load_event

from schedule_foamer.settings import settings

if TYPE_CHECKING:
    from railroad_club.models import GtfsStaticFeed
    from redis import Redis

_client = None


def _redis() -> Redis:
    global _client
    if _client is None:
        import redis

        _client = redis.Redis.from_url(settings.redis_url)
    return _client


def publish_load(feed_id: int, static: GtfsStaticFeed | None) -> None:
    """Push one feed's load status. Never raises."""
    with contextlib.suppress(Exception):
        _redis().publish(feed_channel(feed_id), json.dumps(load_event(static)))
