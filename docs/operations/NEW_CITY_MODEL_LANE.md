# New-City Model Lane (M1)

- **Owns:** the inactive candidate market registry `config/candidate_markets.json`
  (`weather.market.candidate_markets`), the METAR-labelled training-corpus builder
  `weather.calibration.new_city_corpus`, the METAR label and print-cutoff rules for
  candidate cities, what blocks a full corpus, and the R1 recorder-only enable runbook
  for the five pilot cities.
- **Read when:** adding or changing a candidate city, building a new-city training
  corpus, or switching the S2+S9 recorder-only pilot on.
- **Do not use for:** the PIT forecast corpus itself
  ([PIT_FORECAST_TRAINING_CORPUS.md](PIT_FORECAST_TRAINING_CORPUS.md)); the recorder
  internals ([passive-maker-evidence-capture.md](passive-maker-evidence-capture.md));
  which cities and why (the dated phase-2 scoping study, `docs/research/more-markets-phase2-scoping-2026-10-23.md`).
- **Verify with:** `python -m weather.market.candidate_markets check`,
  `tests/market/test_candidate_markets.py`, `tests/calibration/test_new_city_corpus.py`.

Owner decisions of 2026-10-23 (DECISION_LOG): new METAR-settled cities are labelled
from free IEM METAR; Europe first; M = 18 target; Hong Kong recorder-only; Denver
settles on KDEN from the 10-23 events and gets its own model, never the KBKF model.

## Candidate registry: inactive by construction

`config/candidate_markets.json` uses the external market-registry schema but is
**not** the default external registry (`config/markets.json`). So:

- `all_specs()`, `spec_for_id` and `spec_for_slug` in every capture loop, supervisor,
  serving, release and Scheduler path are unchanged by a row added there.
- A workstation process opts in only by setting `WEATHER_MARKET_REGISTRY` to the file
  (the documented non-live override). International live paths refuse that variable
  (`weather.operations.live_path_security`).
- Every row has `lifecycle: candidate` and no `enabled` switch; the loader refuses any
  other lifecycle, unknown fields, and any id, station or slug prefix that collides
  with a built-in.
- `replaces_builtin` marks a station change of an existing venue series (only
  `denver-kden` today). Such a row shares only the built-in's slug prefix, timezone and
  unit, never its id or station. With the override loaded the built-in still comes
  first in slug lookup, so the live KBKF Denver market is unchanged.
- Activation is a separate reviewed `MarketSpec` change in
  `src/weather/market/market_registry.py`, with its own roll verdict.

The tests prove it: the default registry never contains a candidate; a static import
walk from the capture loops, the execution tape, the supervisor, `thin_ensure`,
`daily_refresh`, the 88a recorder and `release_serving` (module and deferred edges)
never reaches either candidate module; nothing under `src/`, `app/`, `scripts/` or
`config/scheduled_tasks.json` names the file.

Per row: station ICAO from the venue's `resolution_source_url` (`ids=`) in
`config/location_market_events.json`, IANA zone and unit from `config/locations.json`
(a test binds all three), `open_meteo_model: gfs_seamless` (London's `best_match`
starts only in 2024-03). The European zones leave summer time on 2026-10-25 (a
25-hour local day); every date in this lane comes from `zoneinfo`, never a fixed
offset. `denver-kden` coordinates are the KDEN airport reference point, not a
station-catalogue position.

## Label and print-cutoff rules

- **Label (`label_sources.iem_metar`).** IEM ASOS `tmpc`, deduplicated on station and
  observation time, local date from the observation instant in the market zone,
  maximum half-up to a whole native degree. A day is `label_complete` only when no gap
  between reports (local midnight to local midnight) exceeds 180 minutes **and** the
  day lies inside the span the input files cover. Incomplete days never label.
- **Interim.** The builder today admits routine and special reports (the repo's METAR
  rule). The owner's venue rule is the highest **routine** METAR, SPECI excluded,
  tenths from the RMK T-group, native unit. Lane A1's shared label module
  (`claude/venue-rule-labels-20261023`) owns that rule; `daily_label` is replaced by it
  once it is pushed, not re-implemented here. The venue rule needs the raw METAR text,
  so the full download must request `data=metar`. IEM types foreign :20 half-hourly
  routine reports as `report_type=4`, so "routine" for foreign stations cannot be
  `report_type=3` alone (METAR-vs-WU study, 2026-10-23).
- **Print cutoff (`print_cutoffs.metar_observation_time`).** The METAR equivalent of the
  effective WU print cutoff: cutoff hours 07-20 local; only reports observed at or
  before the local cutoff instant are admitted; the effective cutoff is the latest
  cutoff hour the newest admitted report has reached, a report up to 10 minutes before
  the hour counting for it. The hours and alias window are bound by test to
  `INTRADAY_CUTOFF_HOURS` and `SETTLEMENT_PRINT_ALIAS_WINDOW_MINUTES`. Changing the
  served label to METAR for these cities is still a train/serve parity change when the
  model lane is served.

## Corpus builder

```powershell
python -m weather.calibration.new_city_corpus labels --market london --metar-csv <EGLC_rt3.csv> <EGLC_rt4.csv> --last-date 2026-09-29 --out <labels.jsonl>
python -m weather.calibration.new_city_corpus build --markets london,paris,munich,madrid --metar-csv-dir <dir> --pit-corpus-manifest <corpus>\manifest.json --last-date 2025-12-31 --publish-root data\training\new_city_corpus
```

`build` reads `<ICAO>*.csv` per market, drops rows after `--last-date` at read time,
verifies the PIT corpus file hash, refuses a PIT row whose cutoff instant disagrees or
whose issue or availability time is after the cutoff, joins only complete labels, and
publishes `rows.jsonl`, `labels.jsonl` and `manifest.json` atomically under
`corpora/<sha256>`; an existing corpus is never overwritten. It never fetches.

## What blocks a full corpus

1. **Wrapper allowlist.** `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy`
   refuses every fetch module (`weather.sources.forecast_training_corpus_fetch`,
   `weather.sources.forecast_history`, `weather.sources.metar_history`) and any script
   path: none is in `Get-WeatherWorkstationOfflineModule`. A reviewed allowlist change
   is needed before either approved download can run under the wrapper.
2. **Open-Meteo collector not on master.** The PIT collector
   `weather.sources.forecast_training_corpus_fetch` and the planner's `--fields` and
   `--pad-request-days` exist only on `claude/pit-corpus-fetch-20261021` (also in the
   R0 branches). Once landed and allowlisted, with
   `WEATHER_MARKET_REGISTRY=config\candidate_markets.json`:
   `plan --years 2021,2022,2023,2024,2025 --markets london,paris,munich,madrid,denver-kden --season-start 01-01 --season-end 12-31 --fields temperature_2m --pad-request-days 1`
   (check the padded-December rule in the PIT runbook before planning 2025), then the
   collector, `resume-status` and `materialize`.
3. **IEM METAR history.** Owner-approved 2026-10-23 for EGLC, LFPB, EDDM, LEMD, RKSI,
   RJTT, ZSPD and KDEN, UTC 2021-01-01..2026-09-30, routine (`report_type=3`) and
   special (`report_type=4`) fetched separately with `tmpc` and `metar`, serial and
   a few seconds apart. Blocked by item 1 only.
4. **Venue-rule label module** (lane A1), not yet pushed.

## R1: recorder-only enable for the five pilot cities

Scope: London, Paris, Seoul, Tokyo, Shanghai, the `core_recorder_only.rows` already in
`config/capture_families.json` on the S2+S9 integration head. Run on the morning after
S2+S9 lands. Recorder-only: no capture family, model, serving or settlement input;
nothing is registered. `config/` is roll-free, and the running 88a recorder re-reads
the block every cycle (no restart).

**Checks before the flip (all must pass; any failure means stay off):**

1. S2+S9 is on `origin/master` and the production tip contains it.
2. The S2+S9 day-1 receipt from the landing night passes its own checks: zero 429s,
   REST within budget, built-in selection unchanged, no graded-loop readoption, the
   88a restart gap recorded in the panel notes.
3. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\status.ps1`:
   `MAKER` line `CAPTURING`, `maker_evidence_code` `CURRENT`, `PILOT` line `off` with no
   `MAKER_EVIDENCE_PILOT` or `CAPTURE_REGISTRY` warning (the rows validate every cycle).
4. Free space on C: (volume free bytes, `Get-Volume -DriveLetter C`) at or above
   70 GiB, the pilot's stop band.
5. `scripts\ops\roll_verdict.ps1 -Branch <flip branch>` returns ROLL-FREE for the
   one-file diff.

**Flip.** On a branch from `origin/master`, set `core_recorder_only.pilot` and
`core_recorder_only.rewards_sweep` to `"on"` in `config/capture_families.json`; leave
`built_in_reward_cadence` at `legacy` (it cannot act before 2026-10-31T00:00Z). Land
through the roll-free path, then confirm the next cycle:

- `status.ps1` shows `PILOT` capturing, not `DEGRADED` or `CONFIG_ERROR`.
- Pilot partitions appear (`discovery-pilot`, `universe-pilot-<id>`, rewards `-pilot`,
  `trades-pilot.jsonl`) and no pilot token is in `books.jsonl` or `trades.jsonl`.

**24-hour acceptance** (the S2+S9 plan row): REST at or below 0.4 req/s after the
cadence flip and zero 429s; five pilot partitions sealed and gzip-verified; at most
10 MB per city-day; RSS at most 80 MiB; `peak_raw_working_bytes` recorded; built-in
selection unchanged; held segments untouched.

**Rollback.** Set `pilot` and `rewards_sweep` back to `"off"` and land the same way;
the recorder stops pilot reads on its next cycle. Pilot partitions already written are
evidence: keep them, never delete them.

## Update this file when

Update when a candidate row, the candidate schema, the label or print-cutoff rule,
the corpus builder CLI, a blocker, or the R1 checks change.
