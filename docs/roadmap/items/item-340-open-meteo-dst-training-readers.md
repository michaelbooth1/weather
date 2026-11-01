# 340. Open-Meteo DST Fix For Training And Backfill Readers [OPEN 2026-11-01 - R26 RE-TIP BUILT; LANDS ROLL-SENSITIVE AS ITS OWN SUITE HEAD]

Goal: every training and backfill reader of Open-Meteo hourly payloads places each naive label with the response's
own `utc_offset_seconds`, through the one shared conversion `weather.time.provider_hourly_local_times`, and refuses a
row whose naive label has no usable response offset, or whose naive labels are not one uniform series, instead of
guessing.

**Supersedes `a399941e`** (master ruling R26, 2026-11-01). Both change the same four readers at the same call sites;
`a399941e` (`claude/dst-training-readers-fix-20261021`) falls back to the zone-local reading where this item refuses.
`a399941e` is retired without landing; its branch is kept. The R26 re-tip is
`claude/om-dst-readers-ab-r2-20261104`, cut from `2638fdee1`.

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
- R26 step 1: with a usable offset, naive labels that repeat, gap, or hold an unparseable label mid-series produce no
  row (`REFUSED_NOT_FIXED_OFFSET`, `weather.sources.open_meteo_label_times`); an unparseable label at either end is
  no gap and drops only its own row.
- R26 step 2: every refused row is counted. The archive normalizers return `offset_refused_row_count` (and the write
  results `offset_refused_rows`); the `forecast_history` backfill manifest carries `offset_refused_rows` per source.
- R26 step 3: `ReanalysisStore.offset_refused_row_count()` is one raw-payload pass outside `coverage()` (the data-layer
  audit also calls `coverage()`); the Stage-A reanalysis step calls it once per market and reports the total.
- R26 step 4: `a399941e`'s spring-forward test is ported unchanged and its unparseable-label test with the
  expectation reversed (`tests/sources/test_training_reader_dst_labels.py`).
- A payload whose offset matches the zone reads unchanged.
- Roll verdict from master's `roll_verdict.ps1` before any merge. Head A may be roll-sensitive because
  `model/feature_store` imports `reanalysis_synoptic`.

Status:

- [x] P0 audit (read-only, 2026-10-27): serving does not read `forecast_history` labels; MG-1/MG-2 inputs do not
  import these readers; the local archives hold no standard-time dates. Capture-host archives were not checked.
- [x] Head A and head B built and merged into `2638fdee1` (combined pregate tip).
- [x] R26 re-tip (`claude/om-dst-readers-ab-r2-20261104`): steps 1-4 and 7 built and tested on the workstation.
- [ ] Merge `origin/master` after the previous night's landings are published; WS bounded suite on the exact tip.
- [ ] Landing: roll-sensitive (`reanalysis_history` and `reanalysis_synoptic` are loop-imported), its own suite head,
  target night 11-04/05; host `roll_verdict`, merge-tree simulation and B guard first.
- [ ] EF §10w entry updated on a separate docs head after landing.

Not claimed: reading by the response offset moves the hours at a payload's edges across midnight, so a day at the
edge of a payload can gain or lose an hour; this item does not stitch adjacent payloads.
