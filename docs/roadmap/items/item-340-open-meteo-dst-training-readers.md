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
- R26 step 5, master's option (b): the reanalysis store drops a local day that falls before the archive's first
  payload range start or after its last range end (`inside_archive`, `ReanalysisStore.archive_bounds`). Those are the
  only partial days the response offset creates at the archive edges: a summer download of a winter first date puts
  that date's 00:00 label at 23:00 on the previous day as a one-row day. A day inside the archive is never dropped,
  so DST days keep their 23/25 rows. The dropped dates and their count go into the rebuild manifest
  (`archive_edge_dropped_dates`, `archive_edge_days_dropped`) and the rebuild CLI line. The same rule bounds
  `raw_normalizable_dates`, `raw_variable_covered_dates` and `reanalysis_synoptic.load_raw_daily_metrics` (the
  antecedent sums).
- A payload whose offset matches the zone reads unchanged.
- Roll verdict from master's `roll_verdict.ps1` before any merge. Head A may be roll-sensitive because
  `model/feature_store` imports `reanalysis_synoptic`.

Status:

- [x] P0 audit (read-only, 2026-10-27): serving does not read `forecast_history` labels; MG-1/MG-2 inputs do not
  import these readers; the local archives hold no standard-time dates. Capture-host archives were not checked.
- [x] Head A and head B built and merged into `2638fdee1` (combined pregate tip).
- [x] R26 re-tip (`claude/om-dst-readers-ab-r2-20261104`): steps 1-4 and 7 built and tested on the workstation.
- [x] R26 step 5 (workstation copies, every range ending 2026-08-10): no payload lacks a usable offset and none has
  a non-uniform series. Chicago scratch rebuild row counts before the duplicate-chunk dedupe: 23:25, 24:8833,
  25:25, >=26:778, none <=22. The edge rule drops one day per market (1999-12-31), 12 across the 12 markets.
- [ ] Merge `origin/master` after the previous night's landings are published; WS bounded suite on the exact tip.
- [ ] Landing: roll-sensitive (`reanalysis_history` and `reanalysis_synoptic` are loop-imported), its own suite head,
  target night 11-04/05; host `roll_verdict`, merge-tree simulation and B guard first.
- [ ] EF §10w entry updated on a separate docs head after landing.

Duplicate chunks (pre-existing; master ruled it model-relevant, so it is fixed in this head): the workstation
reanalysis copies hold overlapping raw payloads for 2024-2026. Two 30-day chunk series are offset by one day, and
each chunk shares its edge day with the next. Read as is, about 778 Chicago days carried about 48 hourly rows. That
doubled `row_count`, `max_temp_times` and the synoptic sums (precipitation, ET0, shortwave and the 7/14/30-day
antecedent windows), and reweighted means on partly duplicated days. Maxima and minima were unaffected.

- Fix: `ReanalysisStore.rebuild` (`dedupe_hourly_records`) and `reanalysis_synoptic.load_raw_daily_metrics` keep
  one copy per UTC hour: the first in raw-file order.
- Audit trail: the rebuild manifest records `duplicate_hours_dropped`, plus `duplicate_disagreement_days` and
  `duplicate_disagreement_dates` for the local dates where a dropped copy's record differed from the kept one (the
  generation-time field is ignored). Disagreement is judged on the normalized record, not on the extra raw synoptic
  fields.
- Chicago scratch rebuild with the dedupe: 18,882 duplicate hours dropped, none disagreeing. Row counts 23:27,
  24:9608, 25:26, none <=22 or >=26.

`chunk_date_range` never makes two chunks that share an edge day, so the edge-sharing files came from an earlier or
out-of-repo writer. A `backfill` run without `--skip-existing` from a different start date can still add a second,
offset series. The capture-host store may hold the same files; `tools/research/reanalysis_chunk_overlap_census.py`
(its own roll-free branch) counts them there.

Not claimed: reading by the response offset moves the hours at a payload's edges across midnight, so a day at the
edge of a payload can gain or lose an hour; this item does not stitch adjacent payloads.
