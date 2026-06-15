# 61. Supplemental Nearby Station Registry And Provenance [COMPLETE 2026-06-15 - REGISTRY AND PROVENANCE LIVE]

Goal: make validated nearby station roots first-class supplemental sources,
without letting them masquerade as canonical settlement history.

Audit source: `docs/research/HISTORICAL_AND_NEARBY_DATA_AUDIT_2026-06-15.md`.
The Toronto supplemental GHCNh root `data/noaa_ghcnh/cyyz_alt_can06158733`
shows why this matters: it adds 546 target-season days and is useful, but it
must stay provenance-labelled.

Tasks:

- [x] Add a supplemental-station registry keyed by market id and source id.
  Required fields: source type, source id, station id/name, root path,
  latitude/longitude, elevation when known, distance from canonical station,
  validation status, adopted date windows, and reason for adoption.
- [x] Teach historical coverage/audit tools to read the registry instead of
  relying only on `*_alt_*` path conventions.
- [x] Persist provenance in any derived supplemental daily/hourly outputs:
  `source_role=supplemental`, canonical market id, supplemental source id,
  station id, and distance from canonical station.
- [x] Add audit output that distinguishes canonical coverage from canonical +
  supplemental composite coverage.
- [x] Add a guard that prevents supplemental roots from being read through the
  canonical station path by accident.

Acceptance: a reviewer can tell, from the registry and generated audit rows,
exactly which nearby station supplied each supplemental record, how far it is
from the canonical market station, and why it is allowed to be used.

Implementation update (2026-06-15): `config/supplemental_stations.json` is now
the first-class supplemental station registry. It includes the Toronto
`ghcnh_cyyz_alt_can06158733` source with station id/name, root path,
latitude/longitude, distance from CYYZ, validation status, adopted 2000-2012
window, and adoption reason. `src.weather.sources.supplemental_stations`
validates required registry fields, indexes sources by market/source type, maps
roots back to registry entries, and rejects supplemental entries that point at a
canonical source root.

Historical outputs now preserve provenance. The shared historical hourly/daily
schema has optional provenance columns (`source_role`, `canonical_market_id`,
`supplemental_source_id`, `supplemental_station_id`,
`source_distance_from_canonical_km`). Canonical sources default to
`source_role=canonical`; registered supplemental GHCNh rebuilds write
`source_role=supplemental` and the registry source/station/distance fields into
hourly JSONL, daily CSV, and manifest metadata.

The reporting tools now consume the registry instead of `*_alt_*` discovery.
`historical_coverage` emits registered supplemental GHCNh sources under each
market, and `data_layer_audit` builds nearby-source and canonical-plus-
supplemental composite coverage from the registry. The markdown audit table now
shows source id, station id/name, distance, validation status, adopted windows,
reason for adoption, bias metrics, and path.

Verification:

- `pytest tests\sources\test_historical_sources.py tests\reporting\test_data_layer_audit.py -q`
  passed: 29 tests.
- `pytest tests\sources\test_historical_sources.py tests\reporting\test_data_layer_audit.py tests\reporting\test_source_redundancy.py tests\calibration\test_pooled_feature_model.py -q`
  passed: 43 tests.
- `python -m compileall` passed for the supplemental registry, historical
  schema, GHCNh, historical coverage, and data-layer audit modules.
- `python -m src.historical_coverage report --markets toronto --start
  2000-01-01 --end 2000-01-02` reported `ghcnh_supplemental=1`, and the
  generated JSON contained source id `ghcnh_cyyz_alt_can06158733`, station
  `CAN06158733`, `source_role=supplemental`, distance `0.05`, validation
  status, adopted window, and adoption reason.
