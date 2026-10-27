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
- **Venue rule.** Labels come from lane A1's `weather.backtesting.venue_rule_labels`
  (imported, never its CLI, which also fetches): the highest **routine** METAR, SPECI
  excluded, tenths from the RMK T-group (body whole degree when absent, as at every
  European station), half-up to the native whole degree, an accepted correction
  replacing the original.
- **Scheduled type-4 reports.** IEM raw text has no METAR/SPECI prefix and IEM files a
  foreign station's off-hour half-hourly routine reports as `report_type=4`. Measured
  on the 2021-2026 download (2022 files): EGLC and EDDM type 4 is ~8,757 reports at
  :20 and a handful at :50; LFPB, LEMD, RKSI, RJTT and ZSPD ~8,715 at :30 and ~47 at
  :00; KDEN type 4 is ~1,400 a year at scattered minutes (true SPECIs). The venue's
  AviationWeather feed carries those half-hourly reports as METARs. Each candidate row
  therefore declares `iem_special_schedule_minute` (20 or 30; `null` for KDEN): a type-4
  report at exactly that minute with no SPECI prefix is the scheduled routine report;
  every other type-4 report stays special. Without it a European label would be the
  hourly maximum only (the METAR-vs-WU study found the half-hourly reports raise the
  maximum on 6-11 of 60 days per pilot city).
- **Known assumption (master, provisional, 2026-10-24).** The schedule minute is
  per-station config (`iem_special_schedule_minute` on each candidate row), never a
  constant. It stands in for the venue's prefix test because IEM raw text has no
  METAR/SPECI label. Checked from metadata only (public read-only Gamma GET of the
  2026-10-25 London, Paris and NYC events, `resolutionSource` and `description` fields
  only): London and Paris name `aviationweather.gov/api/data/metar?ids=EGLC|LFPB`, and
  their description is the US template word for word except the unit paragraph. It
  says a SPECI-prefixed report "does not count" and that every other report is
  routine, "including one issued off the nominal hour". A true SPECI that IEM files at
  exactly the schedule minute would be mislabelled routine; revisit if AWC raw text for
  these stations ever shows a SPECI at :20 or :30.
- **Features vs labels.** Labels use the routine selection; observed-so-far cutoff
  features use every report (routine and special), as a live station feed does.
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
python -m weather.calibration.new_city_corpus labels --market london --routine-csv <routine csv ...> --special-csv <special csv ...> --last-date 2026-09-29 --out <labels.jsonl>
python -m weather.calibration.new_city_corpus build --markets london,paris,denver-kden --metar-root data\venue_rule_labels\metar --pit-corpus-manifest <corpus>\manifest.json --last-date 2025-12-31 --publish-root data\training\new_city_corpus
```

`build` reads `<icao>/routine/*.csv` and `<icao>/special/*.csv` (the
`venue_rule_labels` METAR layout) per market, drops rows after `--last-date` at read time,
verifies the PIT corpus file hash, refuses a PIT row whose cutoff instant disagrees or
whose issue or availability time is after the cutoff, joins only complete labels, and
publishes `rows.jsonl`, `labels.jsonl` and `manifest.json` atomically under
`corpora/<sha256>`; an existing corpus is never overwritten. It never fetches.

`fit --corpus-manifest <corpus>\manifest.json --train-through 2024-12-31 --test-from
2025-01-01 --test-to 2025-12-31 --out-dir data\training\new_city_corpus\fits` scores,
per market and cutoff, a bias-corrected forecast baseline, OLS and monotone
`HistGradientBoostingRegressor` (sd from 5-fold by-date CV) as normal band ladders
(1 °C or 2 °F). OLS and HGB carry a hard floor: no mass below the rounded highest
label-rule report by the cutoff. Weather-only, no market prices; it refuses a test
window after 2025-12-31. Blocks 07-09, 10-12 and 07-12 are the headline; deltas carry
date-clustered bootstrap CIs.

**Measured (2026-10-24, corpus `d519ab1d…`, fit `92fdffe2…`):** for London, Paris and
KDEN, OLS+floor beats the baseline in every block (07-12 Brier delta −0.042, −0.039,
−0.022, CIs exclude zero). HGB+floor also beats the baseline from 10-12 on but is worse
than OLS+floor in every block except Paris 07-09 (tie), and far worse late in the day
(17-20 Brier +0.14 to +0.41): per-cutoff trees on about 1,350 training days cannot
reproduce the near-identity late-day mapping that OLS fits exactly. OLS+floor is the
candidate; plain HGB is not.

`ols_hgb_resid` (OLS plus an unconstrained HGB on the OLS training residuals, floor
applied after the residual, sd from two-stage out-of-fold residuals) measured on the
same corpus (fit `dd3f032d…`): indistinguishable from OLS+floor. 07-12 Brier versus
OLS: London +0.005 [−0.002, +0.011], Paris −0.003 [−0.010, +0.003], KDEN +0.000
[−0.005, +0.005]; the only CI that excludes zero in a headline block is Paris 07-09
(−0.008 [−0.016, −0.000]). The residual stage adds no measurable skill on these
features.

**Measured (2026-10-25, corpus `f8eaae6b…`, fit `a5d97d49…`, 364 test dates each):**
Munich, Seoul, Tokyo and Shanghai follow the same pattern. OLS+floor beats the
baseline in every headline block (07-12 Brier delta −0.040, −0.096, −0.062, −0.077),
plain HGB+floor is no better than OLS, and residual HGB is indistinguishable from OLS.
**Madrid is the exception:** OLS+floor does not beat the baseline before noon (07-12
−0.003 [−0.008, +0.002]) and gains only from the afternoon on (17-20 −0.625).

## Inputs and how they run

- **IEM METAR history** (owner-approved 2026-10-23): EGLC, LFPB, EDDM, LEMD, RKSI,
  RJTT, ZSPD and KDEN, UTC 2021-01-01..2026-09-30, `report_type=3` and `=4` fetched
  separately with `tmpc` and `metar`, one file per station, type and year, serial,
  5 s apart, resumable. Stored under `data/venue_rule_labels/metar/<icao>/{routine,special}/`
  with `m1_fetch_receipts.jsonl` beside them.
- **Open-Meteo Previous Runs** (owner-approved 2026-10-23): the PIT collector
  `weather.sources.forecast_training_corpus_fetch` with
  `WEATHER_MARKET_REGISTRY=config\candidate_markets.json`, temperature only,
  `gfs_seamless`, lead 1, `--pad-request-days 1`. Network fetches run directly on the
  workstation (master ruling 2026-10-23), serial and resumable; `plan` and
  `materialize` run under `workstation_heavy.ps1`.
- **Provider gap measured (2026-10-23):** `gfs_seamless`
  `temperature_2m_previous_day1` is null at the KDEN point from the start of the
  series through 2021-03-23 17:00 local, so the 2021 plan starts on 03-25. The known
  2023-12-30 gap (PIT runbook) runs at the KDEN point through 2024-01-19 05:00 local,
  so 2023 ends 12-28 and 2024 starts 01-22; 2025 ends 12-30 (padded-December rule).
  One plan per year (`C:\wt\pitfetch-m1\plan-<year>.json`), each materialized as its
  own corpus; `new_city_corpus build` takes all five manifests.
- `new_city_corpus` builds run under `workstation_heavy.ps1 -Kind weather_heavy`.

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
