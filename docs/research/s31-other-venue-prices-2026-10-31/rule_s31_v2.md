# S31 v2 rule (DRAFT, 2026-10-31): coverage-tolerant twin summaries and covered-only placebo donors

Status: DRAFT for master. Lane L14, dev-window ledger row **102** (committed `8a8a3b765` before this file).
Written before the v2 coverage projection and before any venue price read under v2. It sits on top of
`rule_s31_p0.md` (sha256 `d50112cc…`), master AMENDMENT 1 (`amendment_s31_1.md`, `4c29c0bf…`) and
Clarifications 1-5. None of those files is edited. Where v2 states something, v2 wins; everything it does
not state is unchanged.

## 1. Why v2

Row 99's P0 closed UNTESTABLE on coverage, not on signal.

- The v1 twin summary needed all six bins of an event quoted at t_eff. That held on 5,696 of 85,825 KAL fit
  snapshots. The main loss was 48,857 snapshots where at least one bin had no valid quote.
- The v1 placebo (`mr_sweep.p0_candidate`) also needed every band donor covered on all 20 seeds. That
  removed almost everything that was left.

v2 changes exactly these two things. It adds an outcome-blind coverage projection and a power gate, and both
must pass before the freeze.

## 2. Unchanged

- **Regime.** Amendment 1's TWC regime: Kalshi events 08-14..09-29. The 08-14 date is KAL burn-in only.
  Scored dates are the scorecard's 08-15..09-29. Events 08-01..08-13 are in no fit and no score.
- **Quote rule.** The WU-day t_eff = min(t_c, cutoff_hour:00 local). The quote is the latest 1-minute candle
  with `end_period_ts` in [t_eff − 60 min, t_eff], with 0 < bid ≤ ask < 1 and ask − bid ≤ 0.20. The mid is
  (bid + ask)/2.
- **V0 and moments.** V0.1/V0.2 event checks, bin intervals, z and the tail width 2 are unchanged. Moments use
  q = mids/Σ mids, μ_t = Σ q z and σ_t = sqrt(max(Σ q (z − μ_t)², 0.25)).
- **Machinery.** The controls run first and refuse on a miss. The P0 statistic, the tilt, the band signal,
  the 20 placebo seeds (20260921+j), the 10,000 date-clustered draws (seed 20261024), MIN_DATES 20 and
  MIN_SNAPS 1000 are unchanged. BH q is 0.10. Survivors get the w gate.
- **Labels and bounds.** The D3 labels (Clarification 2) are Survivor / KILL at edge size / screen null;
  underpowered for information / UNTESTABLE. They are decided on the Clarification 5 widest of three
  intervals: date-clustered, Clarification 1's non-circular block-3, and REV-2 circular block-3 (B 2000,
  seed 20261024). Δ_edge is 0.224.
- **Data limits.** Nothing after 2026-09-29 is read. FEX makes no `fex_pairs` request.

## 3. Family: K = 2

The BH family is **KAL-MEAN and KAL-WIDTH only (K = 2)**.

**FEX-MEAN stays UNTESTABLE, outside the family.** It is reported with p = 1 and the Clarification 4 reopen
condition, and it is not counted in K. This changes rule §7's K = 3. FEX was never testable (master ruling
2026-10-31), so counting it only diluted BH.

## 4. Twin summary (primary design, fixed now)

**Primary: at least k = 5 of the 6 bins quoted at t_eff; one missing bin is imputed as the complement.**

- **Six bins quoted.** Exactly v1.
- **Five bins quoted.** The missing bin's mid is set to m_miss = max(0, 1 − Σ of the five quoted mids). Then
  the unchanged q, μ_t and σ_t are computed over all six bins.
- **Four or fewer quoted.** The snapshot is uncovered ("fewer than five of six bins quoted").
- **Any bin can be the missing one:** the lower tail, an interior bin, or the upper tail. The receipt counts
  covered snapshots by number of bins quoted (6 or 5) and by the missing bin's position.

Why this design:

- The six bins of a V0-kept event are exhaustive and mutually exclusive (V0.2 tiling). So one missing bin's
  probability is fixed by the other five up to the overround. The imputation adds no free parameter and no
  outcome information.
- It keeps the v1 estimator exactly where v1 had coverage.
- The 60-minute staleness window and the validity checks stay as they are.

Disclosed bias:

- The quoted mids carry the event's overround (Σ of six mids ≠ 1). The complement puts the whole deficit or
  excess on the missing bin, and the max(0, ·) clip makes that one-sided.
- This is a deterministic function of the quotes and is known before any outcome.
- It biases μ_t towards the quoted bins and shrinks σ_t when a tail is missing.

The candidates not chosen (no shopping across them, now or after the run):

1. **k = 6 (v1).** Not chosen: it is the design that closed row 99 UNTESTABLE on coverage.
2. **k = 4 with complement mass split across two missing bins.** Not chosen: the split of the remaining mass
   between two bins is undetermined. Any split, such as equal or by width, is a free parameter. When both
   tails are missing, it moves μ_t and σ_t by an amount the quotes cannot pin down.
3. **Per-bin quote design (each Kalshi bin's mid against the overlapping Polymarket band).** Not chosen:
   - The two venues' bins do not align (Kalshi 2-degree interior bins against our bands). A per-bin mapping
     needs an overlap allocation rule, which is a new free parameter.
   - It changes the arm types from summary signals (C on μ_t, S on σ_t) into a new per-band arm that rule
     §4's band-signal machinery does not define.
   - It would also raise K.
4. **A wider staleness window, for example 120 or 180 minutes.** Not chosen: it changes the amendment's quote
   rule. A stale quote no longer reflects the twin's pool at t_eff, which is the R14 mechanism under test.
5. **Last-trade or close price in place of bid/ask mids.** Not chosen: there is no such field in allowlist B,
   so it would need a new fetch. Trade prints are also sparser than quotes.

## 5. Placebo donors: covered snapshots only, within (market, local hour)

This is new code in `weather.calibration.s31_v2`. `mr_sweep.p0_candidate` and its `donor_ok` are not reused
and not edited.

1. **Pool.** The donor pool is the covered fit snapshots: those with a finite twin value under §4. Cells are
   (market, local hour). In a cell, the covered dates are sorted, and the covered snapshots of one (cell,
   date) are ranked by (`captured_at_utc`, `row_key`).
2. **Per seed.** For each of the 20 seeds: `rng = default_rng(seed)`. Cells are visited in sorted order. A
   cell with at least 2 covered dates draws `market_blend.derangement` over its covered dates. A cell with
   fewer than 2 covered dates draws nothing, as in v1.
3. **Donor.** The covered snapshot of rank r on date d takes, as its donor, the covered snapshot of rank
   min(r, n_d' − 1) on the deranged date d'. The donor is therefore always a covered snapshot on a different
   date in the same (market, local hour).
4. **Seed availability.** Seed j is **available** for a snapshot iff:
   - its cell has at least 2 covered dates, and
   - the donor has the same band count as the snapshot.

   Otherwise seed j is **dropped for that snapshot**, and the snapshot stays.
5. **When a snapshot leaves the population.** A snapshot leaves the placebo population only when no seed is
   available (J_i = 0). In practice that means its cell has fewer than 2 covered dates. These are counted
   separately.
6. **The statistic with dropped seeds.**
   - ρ_c is computed over the population.
   - Placebo j's ρ_pl,j is computed over the population snapshots for which seed j is available.
   - Δ = ρ_c − mean_j ρ_pl,j over the retained seeds, as in rule_mr_sweep. The paired bootstrap uses the same
     date draws for every seed.
7. **Seed-level floor.** A seed whose available population is below MIN_DATES (20) or MIN_SNAPS (1000) is
   dropped entirely. If fewer than **J_MIN = 10** of the 20 seeds remain, the arm is UNTESTABLE.
8. **Disclosed in the receipt.** For each arm:
   - per seed: available snapshots, available dates and dropped snapshots;
   - the dropped (snapshot, seed) pairs, split into "cell under 2 covered dates" and "band-count mismatch";
   - the seeds dropped entirely;
   - the snapshots with J_i = 0.
9. **Diagnostics.**
   - The parent's c-deranged diagnostic and the w gate's placebo use, for each snapshot, its
     lowest-numbered available seed.
   - The by-block and by-market subgroups use the same per-seed availability masks.

## 6. Coverage projection (outcome-blind, before the freeze)

`python -m weather.calibration.s31_v2 project` reads quote **presence** and timestamps only. It applies §4 and
§5 and reports counts.

- **Field allowlists, enforced in code and proved by a test:**
  - Candles: `job`, `run_id`, `ticker`, `end_period_ts`, plus presence (non-null) of `yes_bid_close` and
    `yes_ask_close`. The JSON parser maps every float token to a sentinel, so no bid or ask value is ever
    materialised as a number.
  - Snapshots: `row_key`, `market`, `station`, `date`, `captured_at_utc`, `cutoff_hour`, `local_hour`,
    `n_bands`, read from the manifest-verified `inputs_snapshots.parquet` only. The layout's market, bands and
    labels files are not opened.
  - V0: the metadata extracts (allowlist A and M), as in v1.
- **It is an upper bound.** The value checks (0 < bid ≤ ask < 1, spread ≤ 0.20) need values, so the
  projection treats any quote present on both sides as valid. The run's realised coverage can only be lower.
- **Reported (counts only):**
  - covered fit snapshots by bins quoted (6, 5);
  - population snapshots and dates in the scored table, plus the floors check;
  - the §5 dropped-seed counts and the seeds dropped entirely;
  - the uncovered reasons.

## 7. Power gate (D3, at edge)

Power = Φ(Δ_edge / SE − 1.96), with Δ_edge = 0.224. SE = σ_proj · sqrt(VIF) / sqrt(N_proj).

- **N_proj** is the projected population dates.
- **σ_proj** = σ_d(KAL) · sqrt(S_full / S_proj).
  - σ_d(KAL) = 0.09488 (Clarification 1 §2).
  - S_full is the mean KAL snapshots per scored date in the fit table, and S_proj is the projected mean
    population snapshots per population date.
  - This is the same 1/size variance scaling that Clarification 1 used for 11 → 7 markets. It is disclosed
    as an approximation.
- **VIF per REV-2.** VIF = max(1, (1 + ρ)/(1 − ρ), ratio²).
  - ρ = 0.2719 is the lag-1 autocorrelation of row 78's per-date d_t (rows sha256 `c1bfe405…`).
  - The ratio is the REV-2 **circular** block-3 SD of the mean (`s31_p0.block_counts_circular`, B 2000,
    seed 20261024) on those d_t, divided by the iid SD/sqrt(N).
- **Decision.**
  - If power ≥ 0.5 and the projected population meets MIN_DATES and MIN_SNAPS: freeze, and run only after
    the coordinator's admit.
  - Otherwise: record **"UNTESTABLE at edge"** for both KAL arms and stop.
- **Where the numbers go.** The projection and power numbers are recorded in a separate projection note next
  to this file, so this file's sha stays the drafted one.

## 8. Outputs and provenance

The run writes `s31_v2.json`, which is never overwritten, and `s31_v2_rows.jsonl`. It pins this rule, the
amendment, Clarifications 1-5 and the input shas, and it repeats v1's run-tree origin check.

Everything (rule, projection, receipt, logs) is archived under
`C:\archive\ruled-out\s31-other-venue-prices\v2\` with SHA256SUMS, and nothing is ever deleted.
