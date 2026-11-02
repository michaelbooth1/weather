# L47 X36 reopen test on NBM v5.0: rule (frozen before any label read, 2026-11-01)

- Ledger: C row 111 (count 210). No K row until step 3 is reported. Lane L47. Branch
  `claude/x36-v5-reopen-20261101` from `3f3fe50a1f61ac37f225839b2bdc8f9fd0a1dcbf`.
- This file is frozen once its sha256 is reported. Any change is a new file with a new sha.
- **Nothing in this rule reads a date >= 2026-05-27.** The sealed panel is 05-27..07-30 and dev follows. No 88a,
  panel, B forward cell or settlement data for 09-30..10-15 is read.

## Question

Register X36 (R-M) killed the per-market centre shift at gate 1 on 2021-25 LOYO. Its fitted shifts were all
within ±0.4 °F. Its own reopen condition is "a new training corpus shows a fitted per-market shift beyond ±1 °F".
2021-25 is NBM v4.0-v4.3. Two facts suggest serving differs:
- Morning-loss Analysis 5 (dev 2026) has the NBM v2 mean +0.74 °F and p50 +0.83 °F warm against the outcome at
  07-12, against the market's +0.02.
- X35 records a v5.0 product change.

This rule measures the raw NBM-minus-outcome shift on 2026 dates outside dev and the panel.

## Step 1 result (version date), measured before this rule and input-only

The `blend_nbptx` bulletin header on `noaa-nbm-grib2-pds` (the same header that parser v2 reads into
`product_version`) shows:
- `V4.3` through 2026-05-05 07Z;
- `V5.0` from 2026-05-05 12Z;
- 07Z V5.0 from 2026-05-06.

Probes, run directly, with first-300-byte HTTP Range reads only:
- `C:\t\L47b\probe\nbm_version_probe.py` sha256 `deb13069f925cb65019149d4f957e783a388580adbab2cb081b686a2b21f69ed`
  (bisection 2025-06-01..2026-09-01);
- `C:\t\L47b\probe\nbm_version_spot.py` sha256 `382bd0cf8b856a0e5ab83509a8f35750a58b95f49c81a1f1bf24da894c2cea50`
  (spot checks 01-01, 02-15, 04-30, 05-05 12Z/19Z, 05-06 00Z/01Z, 05-10, 05-15, 05-20, 05-26, 05-27).

No NOAA service-change notice was opened. The header is the citation, and the corpus records it per row.

So the window 2026-01-01..05-26 holds:
- **v4.3 on 01-01..05-05 (125 target dates);**
- **v5.0 on 05-06..05-26 (21 target dates).**

## Corpus

- **Inputs.** NBP 07Z bulletin for each target date 2026-01-01..2026-05-26, fetched the L9 way:
  - `tools/research/ols_floor_ladder_nbm_fetch.py --dates-file <list> --cycles 07`, which uses Range reads of
    the 11 US station blocks;
  - parsed with `weather.sources.nbm_probabilistic_tmax.parse_nbp_station_tmax` (parser v2), exactly as
    `ols_floor_ladder._nbm_corpus_command` does;
  - the value is `mean_native` (°F), the NBP TXN mean for the target date. `product_version` is kept per row.
- **Labels.** The WU daily summary `data/wunderground/<station>/daily/daily_summary.csv`, read with
  `weather.backtesting.venue_rule_labels.read_wu_rows`. The label is `weather.sources.daily_summary.native_high`
  (°F) for the market's local date = the target date. Rows are filtered by date before any value is read.
- **Markets.** The 11 US markets of `ols_floor_ladder.NBM_STATIONS`. Toronto is excluded.
- **Refusals.** The code refuses any target date outside 2026-01-01..2026-05-26 for the 2026 corpus. This
  check applies at the dates file, the blocks and the labels.
- **Training-era context only.** The same d over L9's corpus (`C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl`,
  corpus id `1ae4bf52…`, 2021-25, Aug 1..Sep 29 and Oct 3..Dec 16, 07Z, v4.0-v4.3), with WU labels for those
  dates. It is computed per market and season and is never decisive.

## Count first (rule 16), before any statistic

For each market × month (and version within May), report:
- NBP rows available or missing, with reasons;
- WU labels present or missing (the count only says whether `native_high` is non-null; no value is summarised);
- matched pairs.

**STOP and report** if WU labels for Jan-May 2026 are absent for the window, below 80% of target dates in any
market, or below 80% pooled. In that case, report what a free, official fetch would take, and compute nothing
further.

## Statistic

Per matched row, d = NBP mean − WU native_high (°F).

- **Primary.** The per-market mean d over all matched 2026-01-01..05-26 dates, with a 95% percentile interval
  from a date bootstrap (2000 draws, seed 20261024).
- **Also reported:**
  - per market × month;
  - per market by version block (v4.3 01-01..05-05; v5.0 05-06..05-26);
  - pooled over markets, with date-clustered intervals;
  - the within-May version contrast (v5.0 May minus v4.3 May) per market and pooled. v4.3 has only 5 May dates,
    so this is descriptive only;
  - the training-era d per market and season (context);
  - mean |d| and the SD of d per cell.

## Decision (X36's own condition, as the coordinator set it)

- **REOPEN** if any market's primary mean d has |point| > 1.0 °F and its 95% interval excludes 0. Then draft,
  but do not run, a rule for a v5.0-aware centre correction: a version term, or a trailing PIT-bias window over
  strictly earlier dates. It is trained without dev or panel dates, with dev as the refutation gate.
- **NOT REOPENED** if every market's primary |point| <= 1.0 °F, or no market with |point| > 1.0 has an interval
  excluding 0. The report then states what the version-block and month cells show. For example, a v5.0-block or
  May-only excursion beyond 1 °F narrows the mechanism to season × version and is a lead, never a reopen.
- Either way, nothing is fitted to a model, no Brier is computed, and no dev date is read.

## Disclosures, fixed before the read

1. X36's quantity was a fitted shift on the P3d_N_fix residual, which already absorbs the training-era raw NBM
   bias. This rule measures the raw NBM bias. A raw 2026 shift beyond 1 °F that equals the training-era raw
   shift would not be a model shift. The training-era context table exists so master can judge that. It is
   reported, not used to override the decision line.
2. The v5.0 block is 21 dates in May. Its season (late spring) differs from dev (Aug-Sep) and from the
   training era (Aug-Dec). Season and version cannot be separated inside this window.
3. NBP TXN is a daytime-period maximum, while the WU high is the local calendar-day maximum. That structural
   difference is present in every era.
