# Standard-time training audit (lever inventory row 11, 2026-10-30)

Status: dated research note (lane L8), not canonical. Read-only, docs-only. It traces the training-row builders behind
six models (listed in Scope) for one thing: Open-Meteo hourly-derived columns on standard-time dates that pass
through the +1 h readers of [established findings](../../operations/ESTABLISHED_FINDINGS.md) §10w.

Lane L2's 2026-11-01 audit (`4f746abe3827aa76cffa66489643f68f12ae686e`) covered recorders and emitters; this note
covers training only.

**No data was read.** I ran no script. Row counts come from lane L11's measured audit, cited below. No outcome,
label, price, 88a, panel or settlement value was opened.

## Verdict

**No corpus is affected.** No frozen or bound model was trained on shifted values.

| Corpus / model | Open-Meteo hourly-derived column in its training rows | Affected rows | Frozen / bound and affected? |
| --- | --- | ---: | --- |
| P3d_N_fwd (MG-2 13-16 state `c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780`) | `fh` fallback only (PIT `forecast_high`, fixed reader) | **0** | Bound; **not affected** |
| SM-N (P3d_N spec on Oct-Dec rows; row 50, not adopted) | same as P3d_N | **0** | Never built as a state |
| SM-L6 (season-matched L6 state `800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db`) | none (IEM ASOS only) | **0 by construction** | Bound in MG-2 / B; **not affected** |
| L6_G (frozen shift `ae95686b5468bceed0fd33ead0f397dc061d9a5822f56bfb2364814553e8983e`) | none; fitted on dev 08-01..09-29, all daylight time | **0 by construction** | Frozen; **not affected** |
| PT-1 candidate C-PT (MG-2 pre-13 L6 part `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9`) | none (L6 part plus the SM-L6 or Aug-Sep L6 state; w_h on dev ≤ 09-29) | **0 by construction** | To be bound; **not affected** |
| MG-2 frozen fit (descriptive; B unchanged) | L6 part, SM-L6 state and P3d_N state, as above | **0** | Bound; **not affected** |

The +1 h readers in §10w are:
- `forecast_history.local_valid_datetime`;
- `open_meteo_archives`;
- `reanalysis_history`;
- `historical_fallbacks`;
- the pre-fix `forecast_training_corpus` labeler.

None of them reaches a training column of these six models. The one column that can carry Open-Meteo hourly values
on standard-time dates is the P3d_N anchor fallback. It is built by the **fixed** corpus labeler, and L11 measured it
at 0 misaligned.

## Scope

Six training sets: P3d_N_fwd, SM-L6, SM-N, L6_G, the PT-1 candidate, and MG-2's frozen fit (descriptive only).

**Standard-time dates in the training years (2021-25):**
- they run from the fall-back Sunday to Dec 31;
- the fall-back Sundays are 2021-11-07, 2022-11-06, 2023-11-05, 2024-11-03 and 2025-11-02;
- no training set here uses Jan-Mar rows.

## Code trace (origin/master `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de` unless stated)

### P3d_N_fwd, SM-N, and MG-2's 13-16 state

**Builder.**
- `pooled_residual_model.extract_market` builds the records with `feature_model.build_feature_records_for_model`.
- It passes `forecast_resolver = PITForecastCorpusUnion(...)`, so the ambient `forecast_daily.csv` analogs (the
  `forecast_history` path) are not read.
- `forward_fit` reads `forward_training_frame`, which drops every `x_` column except
  `DEV_KEEP_X = ("x_high_so_far", "x_current_temp")`.
- It then replaces `fh` with the NBM mean through `attach_training_nbm`.
- It fits with `raw_columns=False`.

**Model inputs.** The fitted inputs are:
- `F` = high_so_far;
- `current_temp`;
- `fh` = the NBM mean, or `forecast_high` where the NBM is missing;
- day of year, lat, lon, elevation, and the bias and normal terms;
- `y`.

**Each input against the §10w readers:**
- **`high_so_far`, `current_temp`.**
  - They come from `model_climatology.historical_target_cache`, which reads WU `hourly/.../observations.jsonl`.
  - `local_date` and `local_time` are written by `wu_history.local_datetime`: epoch `valid_time_gmt`, then
    `astimezone(tz)`. This is zone-aware.
  - The cutoff is `minute_of_day <= hour * 60` plus `wall_offset_for`, a deterministic intra-hour offset with no
    time-zone term.
  - Not a §10w reader.
- **NBM `fh`.**
  - `ols_floor_ladder.nbm_at_cutoff` → `_cutoff_instant` builds the local hour with `ZoneInfo(tz)` and converts it
    to UTC.
  - `LastModified` is UTC.
  - Not affected.
- **`forecast_high` fallback** (records with no NBM value; the provenance key is `train_nbm_imputed_forecast`).
  - It comes from the PIT corpus's materialized `forecast_daily.jsonl`.
  - The labeler that wrote those rows is `forecast_training_corpus.resolve_provider_times`: label minus
    `utc_offset_seconds` gives UTC, then the market zone.
  - It landed as `b3d7eb77526da6f5c858c47496a369357989cd6c` (2026-10-21 18:16 -0400) on the PIT-fetch branch.
  - The Oct-Dec 2021-23 collection ran from `072f4d5b9f121d411439cb0c14880b8152b44004`, which contains it
    ([PIT corpus doc](../../operations/PIT_FORECAST_TRAINING_CORPUS.md), "Measured provider gap").
  - The 2024-25 Oct-Dec corpus `74807fbe…` was collected later. It is covered by L11's measurement below.
- **Reanalysis columns.**
  - `extract_market` does pass `load_reanalysis_synoptic_features`. That is a §10w reader, shifted on standard-time
    dates per `a399941e`.
  - The `reanalysis_*` record columns are dropped by `DEV_KEEP_X` before any fit, so they cannot enter P3d_N or SM-N
    in code.
  - L11 also found them null in every sampled record file.
- **Marine columns.** `marine_context` reads CO-OPS `lst_ldt`, which is true local time (§10w "Not affected"). The
  P3d spec drops these columns anyway.

**Measured (lane L11, `38bab7f9c5c3329921c2ee0d511a31aedcd4e471`, `docs/research/permarket-bias-l11-2026-10-26/results-dst-audit-octdec.md` on `origin/claude/permarket-bias-20261026`).**
- **Record set.**
  - It covers the same Oct-Dec trainer record set that Clarification 3 names for the forward state:
    - corpora `cd0ba2bb004dc89f070ec9b1406e77f38cd2396dedd93ce1b377e727baefe9be`,
      `23ac87fa5f058f8eeb7f49f0268f483939d4070f7f65e38063727c6749aa2a8d` and `74807fbe…`;
    - centres 10-10, 10-25, 11-09, 11-24 and 12-09, the Oct-Dec half of `FORWARD_CENTRES`.
  - Size: 57,736 records, of which 31,878 are on standard-time dates, 25,088 on daylight-time dates and 770 on the
    change day.
- **Misaligned: 0 on every check.**
  - PIT hourly rows: 73,128 standard-time / 45,672 daylight / 1,375 change-day.
  - PIT daily rows: 42,658 / 26,642 / 770.
  - The WU print cutoff, which includes a recompute of high_so_far.
  - NBM cycle selection.
- **Aug-Sep rows.** The Aug-Sep half (`b455bd53…`) contains no standard-time date.

**Count of affected rows: 0.** The number of standard-time rows that use the `forecast_high` fallback is not in any
pushed document. It would be a provenance count in the state sidecar, and reading it is not needed for this verdict.

### SM-L6 (and the frozen Aug-Sep L6 HGB)

**Builder.** On `origin/claude/cool-season-audit-20261026`:
- `season_matched_l6.py` calls `upstream_obs_screen.build_history(...)` and keeps `TRAIN_MONTHS = (10, 11, 12)`.
- It fits `make_model(OWN)`.
- `l6_own_state.py` does the same on months (8, 9) for the Aug-Sep state.

**Inputs.**
- `OWN` is hour_f, doy, station_code, t, td, r, t_minus_r, tend3, td_tend3, u, v, spd, cover, log_ceiling,
  prev_dmax and prev_minus_t.
- All of them come from the IEM ASOS extract (`free_screens.iem_upstream`).
  - The request uses `tz=Etc/UTC`, and the extract stores `valid_utc`.
  - The local date is `valid_utc.dt.tz_convert(tz)`.
  - The history cutoffs are local H:30 through `tz_localize(tz, ambiguous="NaT", nonexistent="NaT")`. Hours 07-12 are
    never ambiguous.
- No Open-Meteo, forecast_history or reanalysis input.

**Count of affected rows:** 0 by construction. Ledger row 46's Oct-Dec 07-12 LOYO covers 24,381 rows over 375 dates;
none carries an Open-Meteo column.

### L6_G

- **State.** The frozen state `ae95686b…8983e` is the R-O walk-forward grid minimiser. Per the
  [frozen pre-registration](https://github.com/michaelbooth1/weather/blob/04d604340d25be2e98f19e30fc09a1707a1e9fe8/docs/research/gefs-members-l11-2026-10-26/l6g_forward_prereg_FROZEN_2026-10-30.md)
  §4, it was fitted on dev dates 2026-08-01..09-29 only, with no pre-2026 years. Every fit row is on a daylight-time
  date.
- **G.** G is the GEFS member-mean node max from AWS `noaa-gefs-pds` GRIB. The cutoff is the h:00 local instant
  through zoneinfo, and the local-day node filter is zoneinfo (rule R-N). This is not an Open-Meteo hourly reader.
- **Comparator.** The comparator's L6 part and SM-L6 state are covered in the SM-L6 section above.

**Count of affected rows:** 0 by construction.

### PT-1 candidate (C-PT)

- **Candidate.** Per the [PT-1 draft](../../operations/COOL_SEASON_PAPER_TEST_PREREG.md) §2, C-PT is MG-2's pre-13
  half at MG-2's binding hashes: MG-1 plus the L6 stack, part `07a67425…ee17e9`. No refit is made for the cool
  season.
- **L6 part.** The L6 part's (a_h, b_h) were fitted on dev snapshots of 2026-08..09, which are daylight-only.
- **L6 state.** The state behind N is SM-L6 or the frozen Aug-Sep L6 HGB. Both come from the IEM ASOS history (see
  the SM-L6 section).
- **Log-pool weights.** The weights w_h are fitted on dev dates ≤ 2026-09-29, which are daylight-only.

**Count of affected rows:** 0 by construction.

### MG-2 frozen fit (descriptive; B unchanged)

MG-2's frozen fit has three bound pieces, all covered above:
- the L6 part `07a67425…ee17e9`;
- the SM-L6 state `800072c7…e2db`;
- the P3d_N state `c6cc39f7…c780`.

Not affected. This note changes nothing in B or its bound files.

## Not covered, and caveats

- **Readers that §10w lists stay latent.** No corpus above reads them, but they bite any future lever that does:
  - `forecast_history` and the `forecast_daily.csv` analogs, which feed the served HGB's training rather than these
    models;
  - `open_meteo_archives`;
  - `reanalysis_history`;
  - `historical_fallbacks`.

  The interim rule stands: no rebuild of those caches until `a399941e` lands, after 12-21.
- **§1m calendar-extension hours.** That lineage is the workstation 2026-09-01..04 research, not one of these
  corpora.
- **NBM Tmax window.** NBM Tmax is valid at the next day's 00Z, so its local end moves from 20:00 EDT to 19:00 EST
  across the change. This is the product's own definition. Training and serving read the same parser, so this is
  descriptive, not misalignment (L11).
- **Forward side.** Forward and serve-time inputs after 11-01 are L2's audit, not this one.

## Provenance

| Item | Ref / sha |
| --- | --- |
| Code traced | origin/master `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`: `pooled_residual_model.py`, `mg2_p3d_n.py`, `feature_model.py`, `model/model_climatology.py`, `sources/wu_history.py`, `sources/forecast_training_corpus.py`, `ols_floor_ladder.py`, `upstream_obs_screen.py`, `sources/free_screens/iem_upstream.py`, `l6g_forward_frame.py`, `l6g_forward_emit.py` |
| SM-L6 / L6 state builders | `origin/claude/cool-season-audit-20261026`: `season_matched_l6.py`, `l6_own_state.py` |
| L6_G frozen pre-registration | `origin/claude/l6g-prereg-freeze-20261030` @ `04d604340d25be2e98f19e30fc09a1707a1e9fe8` |
| Records, ledger and SoP | `origin/claude/docs-owner-20261030` @ `e759a55d10e31dd48559ef99b9d2959c41271fd3` (ledger rows 46 and 50; l2 rule Clarification 3) |
| Corpus labeler fix | `b3d7eb77526da6f5c858c47496a369357989cd6c`; collection commit `072f4d5b9f121d411439cb0c14880b8152b44004`; gap record `4adc237cb0f2032b5e01c48d9a2ef9b356852b71` |
| L11 measured audit | `38bab7f9c5c3329921c2ee0d511a31aedcd4e471`; script sha256 7013343c9bb0d1e9df383b17700362cc8453b8adefb63647d4b8f28de38dc9a6 |
| L2 forward audit | `4f746abe3827aa76cffa66489643f68f12ae686e` |
