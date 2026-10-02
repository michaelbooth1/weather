# 79. MRMS Radar Precipitation Interruption Layer [COMPLETE 2026-06-16 - MRMS INTERRUPTION REPORTING LIVE]

Goal: add realized radar/QPE evidence for precipitation and convection that can
interrupt daytime heating.

Source audit: `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`.
The audit confirmed public S3 listings for current MRMS `PrecipRate_00.00`
products under dated CONUS prefixes, with 2-minute files available on
2026-06-15.

Why this is missing: the model can use forecast precipitation, cloud, and CAPE
signals, but it does not have a realized radar/QPE source to know whether rain
or convection actually occurred near the station during peak heating.

## Implementation Design

Source strategy:

- Add `weather.sources.mrms_precip` with schema `mrms_precip_v0.1`.
- Build MRMS public-S3 object URL/listing helpers for CONUS
  `PrecipRate_00.00` and QPE-like products, preserving product name, object
  timestamp, product version string, payload hash, and latest-object age.
- Reuse item 76's GRIB probe foundation for compressed MRMS GRIB validation and
  metadata. Nearest-grid extraction remains optional and explicit because this
  environment may not have `wgrib2`.
- Add live fetcher wiring that reports source lag or extraction-unavailable
  metadata instead of converting missing recent objects into no-precip evidence.

Feature strategy:

- Add live-only MRMS precipitation columns to the shared feature schema with
  historical defaults of `None`.
- Derive rolling realized-precipitation features from normalized MRMS rows:
  any precip in the last 15/30/60 minutes, precipitation since 7 AM,
  precipitation since cutoff, and max precip rate during peak heating/since
  cutoff.
- Add a convective-interruption diagnostic only when realized precip aligns
  with forecast CAPE, forecast precipitation probability, or an observed
  stall/drop signal.

Verification:

- Test S3 key parsing/selection, source-lag handling, compressed GRIB probing,
  normalized row provenance, rolling-window features, and live feature
  extraction with a convection-interruption fixture.

Out of scope for this implementation slice:

- Downloading full MRMS grids in tests.
- Bulk historical grid download/storage orchestration.
- Promotion into trained artifacts before settlement-scored evidence is
  reviewed.

Completed implementation slice on 2026-06-15:

- Added `weather.sources.mrms_precip` with MRMS public-S3 object key/listing
  helpers, latest-object lag metadata, compressed GRIB probing through the item
  76 GRIB validation helper, normalized row provenance, and US-only live source
  wiring.
- Bumped the feature schema to `toronto_feature_store_v1.1` and added live-only
  MRMS rolling precipitation/interruption diagnostics with historical `None`
  defaults.
- Registered `mrms_precip` for US markets and added a short observation-source
  cache TTL. Missing recent objects are source-lag evidence, not no-precip
  evidence.

Completed implementation slice on 2026-06-16:

- Added nearest-station `wgrib2` extraction over item 76's GRIB foundation for
  MRMS precip-rate and QPE products.
- Added archive/backfill feature rows that preserve product version, object
  keys, archive availability, and an MRMS pre/post-upgrade warning.
- Added an interruption scoring report grouped by forecast-overcall,
  late-day-continuation failure, and storm-formed market-move cases.

- [x] Use item 76's GRIB extraction foundation to read nearest-station or small
  bounding-box MRMS precip-rate and QPE products.
- [x] Add rolling features for any precip in the last 15/30/60 minutes,
  precipitation since 7 AM, precipitation since cutoff, and max precip rate
  during peak heating.
- [x] Add a convective interruption flag when MRMS precip/radar evidence aligns
  with high CAPE, forecast storm risk, or observed temperature stalls/drops.
- [x] Backfill target-season MRMS features where public archive coverage exists,
  preserving product version and warning about pre/post MRMS upgrade changes.
- [x] Score MRMS features in days where forecasts overcalled highs, late-day
  continuation failed, or the market moved after storms formed.
- [x] Add source-freshness handling so missing recent MRMS objects are treated
  as source lag, not no-precip evidence.

Acceptance: the model can distinguish forecast-only rain risk from realized
precipitation near the market station, and any MRMS-derived feature has enough
archive and freshness metadata to be replayed safely.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - MRMS INTERRUPTION REPORTING LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

## Live listing poll retired (owner decision 2026-10-02)

The live fetcher never got past the listing: `fetch_mrms_precip_for_market` returns
`rows: []` and `available: False` on every call, while storing the whole day's S3
object listing in every captured `replay_inputs.jsonl` row (about 100-200 MB/day of
listing rows that nothing reads). The owner's missing-information plan stopped the poll:
no built-in market declares `mrms_precip` any more, so no capture loop fetches it.

- Training never saw MRMS values (`feature_store` fills every `mrms_*` column with
  `None`), while serving wrote `mrms_row_count = 0.0` and a listing-age
  `mrms_source_lag_minutes`. With no source, serving now writes `None` for every
  `mrms_*` column, which matches training. No served per-market model uses an
  `mrms_*` feature; the shadow pooled candidates that list them were trained on
  all-`None` columns.
- Captured tapes that carry an `mrms_precip` source still replay through
  `derive_mrms_precip_features`; the parser and payload contract versions stay registered.
- The backfill, feature-derivation and scoring helpers in `weather.sources.mrms_precip`
  are unchanged. Re-enabling a live layer needs a real nearest-grid extraction, not the listing.

