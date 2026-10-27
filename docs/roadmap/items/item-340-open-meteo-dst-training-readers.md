# 340. Open-Meteo DST Fix For Training And Backfill Readers [OPEN 2026-10-27 - HEAD A UNDER REVIEW; HEAD B AFTER THE P0 AUDIT]

Goal: every training and backfill reader of Open-Meteo hourly payloads places each naive label with the response's
own `utc_offset_seconds`, through the one shared conversion `weather.time.provider_hourly_local_times`, and refuses a
row whose naive label has no usable response offset instead of guessing.

Owner/package: `src/weather/sources/` (training and backfill readers). The live serving readers already use the shared
conversion and are out of scope.

Source: master-agent rulings of 2026-10-27 on the item-340 re-scope. Defect: [EF §10w](../../operations/ESTABLISHED_FINDINGS.md)
(Open-Meteo hourly labels are fixed-offset per response; read as zone wall time they are 1 h off on the far side of a
DST change, so a summer download of a standard-time date reads +1 h).

Why this matters: a backfill that reads labels as zone wall time moves one hourly value per day across the date
boundary on every date whose offset differs from the offset at download time. That changes daily aggregates used as
training inputs without any visible error.

Scope:

- **Head A** (`claude/om-dst-readers-a-20261027`): `open_meteo_archives` (global-model and air-quality archives) and
  `reanalysis_history` (normalizer and raw-store coverage), plus `reanalysis_synoptic`, which reads raw payloads through
  the same function. The fail-closed rule lives in `weather.sources.open_meteo_label_times`.
- **Head B** (`claude/om-dst-readers-b-20261027`): `forecast_history.local_valid_datetime` (the manual `backfill()`
  path), after the P0 audit of its live reach.
- Out of scope: `forecast_training_corpus` (already uses `resolve_provider_times` on master) and the live fetchers
  (already fixed).

Acceptance:

- A fixture test on each head fails on master and passes on the head: a Chicago payload for 2024-12-10 with a CDT
  response offset puts its first label on 2024-12-09.
- A naive label without a usable `utc_offset_seconds` (missing, string, bool, non-finite, non-integral, out of range)
  produces no row.
- A payload whose offset matches the zone reads unchanged.
- Roll verdict from master's `roll_verdict.ps1` before any merge. Head A may be roll-sensitive because
  `model/feature_store` imports `reanalysis_synoptic`.

Status:

- [x] P0 audit (read-only, 2026-10-27): serving does not read `forecast_history` labels; MG-1/MG-2 inputs do not
  import these readers; the local archives hold no standard-time dates. Capture-host archives were not checked.
- [ ] Head A: pushed for review; roll verdict and landing open.
- [ ] Head B: `forecast_history` reader, fail-closed, with its fixture test.
- [ ] EF §10w entry updated on a separate docs head after landing.
