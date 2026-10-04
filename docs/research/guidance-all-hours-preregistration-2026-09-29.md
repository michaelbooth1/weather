# Guidance at all hours — pre-registration, mission 2026-09-111h

Frozen specification, written 2026-09-29 America/Toronto before any 111h extract exists and
before any score. Committed and pushed on `codex/guidance-all-hours-20260930` before the first
score; do not edit it afterwards. Every Part 2 output header binds this file's SHA-256 and its
freeze commit, and the scorer refuses to run unless the freeze commit is an ancestor of HEAD and
is present on the remote branch. Development reading only: no candidate is fitted, no α is spent,
no reservation is proposed, no serving or model change follows from any result.

Reservation status re-read at freeze: **NONE RESERVED**
([reserved-confirmation-window](../operations/reserved-confirmation-window.md)). Target dates
2026-09-30 onward are never read by this mission (replay-exam panel).

## Inputs

Only the Part 1 table written by production with
`python -m weather.reporting.research.guidance_extract` (`guidance_rows.jsonl.gz`, its
`market_days.jsonl.gz` and `manifest.json`), verified against `SHA256SUMS` after the owner's
transfer. The manifest must name parser worktree HEAD `2e17ce0eb…` and status `COMPLETE`; an
`INCOMPLETE_*` extract is reported, not scored. Rows are the 11 US settlement markets on
promotion-countable market-days, target dates 2026-08-01..2026-09-29 as present in the table.
No other production data, mirror, archive or network source is used.

## Candidates — 81a's C1 and C2, with v2 guidance values

The pure candidate function is 81a's `tools/research/morning_guidance/candidate.py`
(`candidates(bands, served, features)`) unchanged, called with a feature dictionary in which only
the seven NBM value fields and the two recorded-validity flags are replaced:

- `nbm_prob_tmax_p10..p90`, `_mean`, `_stddev` := the row's `v2_p10..v2_p90`, `v2_mean`,
  `v2_stddev` when `v2_status == "available"`, otherwise absent (so the candidate falls back).
- `nbm_prob_tmax_physical_valid_flag` / `_impossible_flag` := recomputed for the v2 values with
  the feature builder's own rule, `FeatureModelMixin.guidance_physical_state` semantics:
  floor = the captured `guidance_physical_floor` feature; margin = 0.5 native-°C equivalent
  (0.9 °F); representative = p90, else mean, else p50; a value below floor − margin is
  impossible; valid (1 / 0) only when none is impossible, or when no `guidance_physical_floor`
  was captured. A partially impossible set is invalid, exactly as captured rows were.
- Every other feature is the captured value. The C1/C2 floor is 81a's: maximum of the finite
  captured `guidance_physical_floor`, `high_so_far`, `trusted_current_max`; none → served.

C1 = floored v2 NBM distribution if eligible, else the captured served vector unchanged.
C2 = 0.5 served + 0.5 C1, floor-masked and renormalized, else served. No other weight, no
recency or age rule, no hour gate, no C3. Invalid served support is an error, not a repair.
The market vector and the winner reach the scorer only.

## Population, weights, strata

Every snapshot row in the table, all local hours. Brier = mean binary squared error over the
complete band support; market = raw `p_market_yes` (81a's market loss). Equal snapshot weights
within a market-day, then equal market-day weights; no hour reweighting. Hour blocks (local,
half-open): **00-05, 06-09, 10-12, 13-16, 17-23**. Strata `before_20260823` / `from_20260823`
are reported separately and, as 81a declared once, also pooled; no stratum is chosen after
results. Tables per block × {before, from, pooled} and for **all hours**.

## Inference and planning

81a's `tools/research/morning_guidance/statistics.py` unchanged: crossed date × market
multinomial bootstrap, 2,000 draws, seed 20260921, percentile 95% intervals; power at a fixed
−0.0075 shift and MDE80 from the centered bootstrap; ratio of mean candidate Brier to mean market
Brier (power at −0.10); 81a's half-development-effect planning (N = 2..45, then 60 … 3650,
market dimension fixed, infinite-date market-only floor). Report market-days, date and market
clusters, changed-row shares and eligibility-reason counts in every cell.

## Primary question and decision rule

81a's pooled US morning C1 − served was **−0.006672**; twice that is **−0.013344** (the
affordability line under crossed clustering, EF §10j).

- **Reaches twice (descriptive):** pooled US all-hours C1 − served estimate ≤ −0.013344.
- **Reaches twice (interval):** its 95% upper bound ≤ −0.013344. Reported beside the estimate.
- Both strata are shown; a pooled pass with opposite-sign strata is reported as such.
- C2 is reported on the same rule; it does not replace C1 as the primary.

## Falsifiers (frozen from the handoff)

1. **Stale 07Z adds nothing:** in each of blocks 13-16 and 17-23 (pooled strata), C1 − served
   estimate ≥ 0 or its 95% interval includes 0 → the afternoon route is falsified for that block.
2. **Pooled effect stays near 81a's:** pooled all-hours C1 − served estimate > −0.013344 → the
   all-hours route is closed for the US markets under the current rules. Stated plainly.

## Positive control (run first, reported before any v2 table)

On the table's rows at 06-09 local with target dates 2026-08-01..2026-09-19, C1 on the
**captured** (v1) features, 81a's exact rule, pooled US. It passes if its estimate lies inside
81a's interval [−0.011525, −0.002373]. The table's population differs from the 79a export
(fresh inventory, no 79a exclusions), so a fail is reported and every v2 table is labelled "stack
not reconciled with 81a" rather than suppressed.

## Uncounted item from EF §10k

Count 79a/81a-scored rows that used a v1 wrong-period value that passed the floor: rows at 06-09
local, target ≤ 2026-09-19, whose captured NBM set is 81a-eligible (complete, ordered, positive
stddev, captured valid flag 1, finite captured floor) and whose manifest token `v1_period` is
`minimum`. Report count, share of eligible rows, market-days, dates and markets, plus the rows
whose period is `unknown` or lack a manifest row (unavailable, not zero). This is a census of the
table's own population, not of the 79a export.

## Not authorized

No refit, weight search, alternate floor, recency rule, hour-gated candidate, confirmation
reservation, α allocation, serving/config/artifact change, production write or Scheduler action.
