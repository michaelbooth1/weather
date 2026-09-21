# Morning guidance candidate pre-registration — mission 2026-09-81a

Frozen specification, 2026-09-21 America/Toronto. This file must be committed,
pushed, and verified on the exact remote branch before the first candidate score.
Its SHA-256 and freeze commit belong in every subsequent output header. Do not
edit this file after publication. This is development on previously inspected
79a dates, not confirmation, alpha spending, training, or promotion.

## Inputs and P0 completed before freeze

Reuse only the local `missing-information-20260921/extracted-1` export:
snapshot SHA-256 `249a9de0da7b41cb8a2ce1f07944e4007c585f601028b73acaae0dd4bd141c2e`,
79a plan SHA-256 `024dbac70c636e42c4f514d66d79fb955c75362c6534892954c05d0bc9e33a81`.
Base: `origin/codex/nbm-candidate-handoff-20260921` at `c471b1a9`.
No new production data, mirror, archive download, or source reconstruction.
Reservation status re-read: **NONE RESERVED**. This mission changes neither
the reservation file nor any alpha ledger.

P0 retained `coverage-2`: 13,584 US morning snapshots, 458 market-days,
42 dates, 11 markets; 6,293 complete valid NBM rows (46.3266%). Of 7,291
incomplete rows, 7,290 explicitly name NBM fields in `guidance_impossible_features`;
one has no NBM feature evidence. All 12: 14,883 snapshots, 499 market-days,
42 dates, 12 markets; fill 42.2831%. Toronto has no NBM. After 10:00 through
12:59, only 17 of 10,707 US rows are complete; 10,690 explicitly name dropped
fields. Thus the matched 79a improvement is strongly conditioned by the floor.

The actual trace is source selection and cached fetch in `model_sources`, NBP
station/target-slot parsing in `nbm_probabilistic_tmax`, `source_data`'s ok and
target-match filter, `model_features.us_guidance_features`' individual-value
floor filter, then `feature_store.audit_row` and `snapshot_store` persistence.
The filter drops values below the guidance floor minus 0.5 native Celsius
equivalent (0.9 F); stddev survives. A partially impossible set gets valid=0.
The export lacks source-status rows, forecast payloads and station NBP archive;
no-feature rows cannot be counted as proved never-fetched or wrong-target.
The 17 surviving later sets have median only 1.08 F above their captured floor.
Issue age and target identity cannot be recovered, so stale issue versus wrong
target versus a genuine low forecast remains unresolved. No candidate score was
computed to make these observations.

Smallest proposed change: retain raw NBP quantiles and issue/target/fetch identity
alongside the filtered features and explicit per-field rejection reasons; use
the full raw distribution with the existing hard floor only in a separately
reviewed experiment. Do not relax the current filter or floor in this mission.

## Exactly two unfitted candidates

Eligibility uses only captured weather features: all p10/p25/p50/p75/p90,
mean and positive stddev finite; quantiles nondecreasing;
`nbm_prob_tmax_physical_valid_flag == 1`; impossible flag not 1; and a finite
captured floor. Validity here means recorded feature validity, **not** proof of
NBP issue/target provenance, which is absent. No additional age, spread,
market, season, outcome or performance selection is permitted.

Floor = maximum of the finite captured `guidance_physical_floor`, `high_so_far`
and `trusted_current_max` features. This conservatively includes the feature
builder's own floor and never substitutes a later observation. Do not use a
pre-07:00 max-since-07:00 sidecar, which may belong to yesterday. If no captured
floor exists, fall back to served. Native units are used without `_c`-based
conversion. Use `methods.band_probabilities`: linear CDF through the five
quantiles, matched normal tails from captured mean/stddev, half-degree band
edges; zero bands wholly below floor bucket `floor(x+0.5)` and renormalize.

- **C1:** eligible snapshot -> that floored NBM distribution; otherwise the
  captured served vector unchanged, element for element.
- **C2:** eligible snapshot -> 0.5 served + 0.5 C1 NBM; apply the same floor
  mask and renormalize. Otherwise served unchanged. No other weight is tried.

Invalid inputs or zero surviving mass produce documented fallback, never row
deletion. Invalid served support is an error, not silently repaired. The market
vector and realized winner are available to the scorer only, never the pure
candidate function. No parameter fitting or C3 is authorized.

## Population, aggregation and reporting

Every snapshot from 06:00 inclusive to 10:00 exclusive on the 79a admitted
boolean `promotion_countable` market-days. Primary: 11 US markets; secondary:
all 12. Existing 79a extraction exclusions remain explicit (no clean-checkout
or fresh-settlement claim). Equal snapshot weights within each market-day,
then equal market-day weights; **no equal-hour reweighting**. Brier = mean
binary squared error over the complete band support. Primary estimand is mean
(candidate minus captured served) Brier. Report ratio of mean candidate Brier
to mean raw captured-market Brier alongside it. Market renormalization is not
a candidate. Count snapshot rows, market-days, dates and markets; report both
raw snapshot changed share and equal-market-day changed share.

Before/from 2026-08-23 are reported separately and **also pooled, declared
here once**. These are all post-July-31 inputs; no earlier artifact regime is
added. Pooled results are a development summary across the settlement-source
transition, not an interchangeable-source claim. No choice of stratum follows
results. Repeat the same tables for 10:00–12:59 as a declared secondary
extension of the rule, not authority to activate it after 10:00.

Independent multinomial date x market (pigeonhole) bootstrap: 2,000 draws,
seed 20260921, percentile 95% intervals. Report power under a fixed negative
0.0075 Brier shift (0.10 ratio/fraction shift where relevant), using centered
bootstrap errors and two-sided descriptive 5% critical absolute error; MDE80
is the smallest beneficial shift attaining 80%. This is sensitivity, not
post-hoc evidence of validity. Degenerate/insufficient support yields unavailable
power/MDE and an explicit warning, never an affirmative null. Candidate levels
and served/market levels get intervals/support; inference is on paired deltas
and ratios. All tables are descriptive, with no confirmatory alpha spent.

## Confirmation sizing and proposed reservation

Freeze date is the America/Toronto date of this file's first commit; first new
eligible date is the next calendar day (expected **2026-09-22**). Both C1 and
C2 remain frozen regardless of which looks better. Propose a separate family
alpha **0.05 one-sided**, Bonferroni **0.025 per candidate**, for future primary
US morning mean delta < 0. All-12, later-hour and stratum development reads
receive no confirmatory alpha. The sealed pre-boundary campaign ledger is not
spent or altered. Owner approval and endpoint-specific null calibration are
required before treating these proposed allocations as authority.

An exact numeric N at half the as-yet-unscored development effect cannot be
known before P2. Freeze its calculation now and fill numbers in the report,
without revising this specification: for each candidate/population/stratum,
let e = max(0, -development mean delta)/2. Retain market-date cell values and
occupancy. For N future dates, independently draw N dates from the empirical
date distribution and M markets from the empirical market distribution (M is
fixed, never increased as N grows). Compute the occupancy-weighted mean with
the same crossed weights; center its 2,000 errors at the development estimate.
At alpha .025, power = fraction(error - e < quantile(error, .025)). Also
evaluate market-only resampling at infinite date N: its nonshrinking uncertainty
can make 80% unattainable. Search N=2..45 individually, then 60, 90, 120, 180,
270, 365, 730, 1460, 3650; refine the first crossing by bisection and report
Monte Carlo resolution (approximately 0.9 percentage points at power .8).
Show both strata and pooled; pooled US is the declared planning summary.
No date count is asserted for a nonbeneficial or market-floor-limited effect.

This is a plug-in planning scenario at half the development effect, not achieved
power or a guarantee under season shift. Keep missingness in every cell: **do
not divide N by guidance fill again**, since fallback rows already dilute both
effect and variance. At 12 admitted market-days/day, 12N days' cells accrue in
N calendar days (11N US); observed all-12 fill .422831 implies roughly 5.074
guidance-bearing market-day equivalents per day, US .463266 -> 5.096. These
are snapshot-equivalent workload illustrations, not independent clusters.
End date = freeze local date + N; missed countable dates delay it.

Exact proposed reservation text, with deterministic P2 substitutions:

> **PROPOSED, NOT ACTIVE.** Reserve target dates 2026-09-22 through
> {freeze date + max(N_C1_US_pooled, N_C2_US_pooled)}, inclusive, for the frozen
> morning C1/C2 candidate family bound to {this file SHA-256 and freeze commit}.
> Primary: equal market-day mean candidate-minus-served Brier, US11,
> 06:00–09:59 local, promotion-countable, crossed date x market inference.
> Family one-sided alpha .05, .025 per candidate; no interim outcome looks.
> Do not read, enumerate outcomes, score, or substitute reserved dates in
> research or MM without a new explicit owner decision. Accrue N new countable
> dates with the declared fixed market support. No model fitting or selection.

If either N is unavailable or the required joint duration exceeds about 45 new
dates, replace that proposal with this exact disposition: **No reservation is
proposed for this season: the frozen two-candidate family cannot reach its
80% half-effect planning target within 45 new dates.** Report the computed
date or why it is unbounded; name the already-downloaded IEM NBS history joined
to older served dates as the cheapest independent alternative, with its
different deterministic product and missing NBP distribution clearly stated.

## Frozen falsifiers and implementation boundary

C1's full-population interval including zero in either stratum, or an absolute
gain below half the 79a matched floored gain (0.00735 before / 0.00738 from),
falsifies the all-row lead as stated. P0's dominant floor drops already show
strong validity selection; do not describe matched scores as unconditional.
C2 worse than both C1 and served supports shared errors, not another tuned
pool. No result authorizes serving, promotion, model/config/artifact changes,
new data access, Scheduler work, live/exchange activity or master merge.
