## v0.2.3 (2026-11-05)

### Fix

- **deps**: db-models v0.3.0, its object store over obstore instead of boto3
- **deps**: upgrade packages with published security advisories

## v0.2.2 (2026-10-02)

### Fix

- **deps**: bump anyio past CVE-2026-63374

## v0.2.1 (2026-10-01)

## v0.2.0 (2026-10-01)

### BREAKING CHANGE

- the module is now gtfs_zone_static_importer

### Feat

- **loader**: load a hosted feed from object storage
- **events**: publish load status on the feed channel
- add max static gtfs file size
- streaming from csv and celery limits
- initial commit

### Fix

- **events**: log a warning when a load-status publish fails
- fix copier apply
- add duplicate job protection
- better handling of error urls
- allow make to find docker
- use the new static gtfs feed model structure

### Refactor

- rename the package to gtfs-zone-static-importer
- rename api to cafe-car
- use railroad-club
