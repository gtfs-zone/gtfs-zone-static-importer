"""Reading a hosted feed's zip out of the store."""

from __future__ import annotations

import pytest
from gtfs_zone_db_models.object_store import ObjectNotFound

from gtfs_zone_static_importer.gtfs_loader import read_gtfs_object

KEY = "feeds/1/abc.zip"


def test_reads_the_object(store):
    store.put(KEY, b"PK\x03\x04payload")
    assert read_gtfs_object(KEY, max_bytes=1024) == b"PK\x03\x04payload"


def test_missing_object_raises_not_found(store):
    with pytest.raises(ObjectNotFound):
        read_gtfs_object(KEY, max_bytes=1024)


def test_object_over_the_cap_is_refused_before_it_is_read(store):
    # An object stored under a higher cap than the one in force now. The upload
    # endpoint already enforced its own; this is the case it cannot cover.
    store.put(KEY, b"x" * 2048)
    with pytest.raises(ValueError, match="over limit"):
        read_gtfs_object(KEY, max_bytes=1024)
