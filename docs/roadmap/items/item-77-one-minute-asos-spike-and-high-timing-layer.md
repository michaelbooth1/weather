# 77. One-Minute ASOS Spike And High-Timing Layer [COMPLETE 2026-06-16 - ASOS 1-MIN GATE LIVE]

Goal: use free IEM/NCEI one-minute ASOS data to improve high-so-far, spike
persistence, and late-day lock-in evidence where station coverage exists.

Source audit: `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`.
The smoke test found usable one-minute LGA data for 2025-06-14, while other
station/date probes returned headers only. Correct IEM station IDs omit the
leading `K`, and availability varies by station and lag.

Why this is missing: the current METAR layer captures hourly plus special
reports. It can miss short high spikes and exact first-reached timing, both of
which matter for WU print-lag, late-day continuation, and high-has-stood logic.

## Implementation Design

Source strategy:

- Add `weather.sources.asos_one_minute` with schema `asos_1min_v0.1`.
- Resolve IEM one-minute station IDs from market ICAO by dropping a leading
  `K` for US stations (`KLGA` -> `LGA`) and explicitly returning unsupported
  metadata for non-US or missing ICAO markets.
- Build IEM one-minute request params for `asos1min.py`, but keep network
  backfills out of this slice. Tests use CSV fixtures.
- Normalize rows without replacing WU, METAR, or settlement-source rows. The
  output source remains `asos_1min` with station, valid time, native temp,
  dewpoint, wind, direction, pressure, raw fields, and provenance fields.

Feature and audit helpers:

- Add availability summaries by market/station/date with row count, expected
  minute count, coverage ratio, first/last minute, and explicit unavailable
  reason.
- Add one-minute high-timing summary features:
  one-minute max-so-far, first-reached minute, high-duration minutes,
  spike-persistence minutes, intra-hour max since the previous hourly print,
  and one-minute minus hourly-METAR high.
- Keep these as source/helper outputs in this slice. They are not added to the
  trained feature schema or live model path until station coverage/bias gates
  pass.

Verification:

- Use fixture CSV rows that include a short spike missed by hourly METAR.
- Test station resolution, unsupported metadata, normalization, availability,
  feature summary, and no-overwrite source naming.

Out of scope for this implementation slice:

- Promotion into trained model features.

Completed implementation slice on 2026-06-15:

- Added `weather.sources.asos_one_minute` with IEM station resolution,
  request parameter construction, CSV normalization, payload provenance, and
  explicit unsupported-market metadata.
- Added availability and high-timing helper outputs for one-minute max,
  first-reached timing, duration/persistence, and hourly-METAR miss/exceed
  diagnostics without promoting them into the trained feature schema.
- Registered schema `asos_1min_v0.1` and covered the helper with fixture tests.

Completion update on 2026-06-16:

- Added `AsosOneMinuteStore` and `AsosOneMinuteClient` for offline-safe IEM
  one-minute ASOS backfills with raw CSV payloads, normalized per-day JSONL
  rows, hourly summaries, daily summaries, and a manifest.
- Added explicit header-only/unavailable day handling so sparse stations do not
  look silently successful.
- Added report helpers comparing one-minute ASOS max/first-reached timing
  against WU settlement buckets and WU print timing, plus a late-day lock-in
  evidence summary.
- Extended observation-trigger replay output with ASOS one-minute evidence
  columns for WU lag/catch-up cases.
- Added an adoption gate requiring coverage, bias, exact-bucket agreement, and
  source-lag checks before a market can use ASOS one-minute evidence beyond
  report-only diagnostics.

- [x] Build an availability audit by market, station, year, and target-season
  day for IEM one-minute ASOS variables `tmpf`, `dwpf`, wind, direction, and
  pressure where supported.
- [x] Add a station-id resolver that maps market ICAO to IEM one-minute station
  IDs and records unsupported or sparse stations as explicit source-unavailable
  metadata.
- [x] Backfill one-minute rows for markets with sufficient coverage, storing
  raw payloads and normalized hourly/daily summaries without replacing METAR or
  WU settlement-source rows.
- [x] Add features for one-minute max-so-far, first-reached time, high duration,
  spike persistence, intra-hour max since last WU print, and one-minute versus
  hourly METAR miss/exceed.
- [x] Extend late-day lock-in and observation-trigger replay reports to compare
  one-minute ASOS evidence against WU final settlement and WU print timing.
- [x] Gate market adoption by station-specific coverage, bias, exact-bucket
  agreement, and source lag.

Acceptance: one-minute ASOS is used only for markets with validated station/day
coverage, exposes spike/high-timing features with provenance, and never silently
overwrites WU or existing METAR truth proxies.
