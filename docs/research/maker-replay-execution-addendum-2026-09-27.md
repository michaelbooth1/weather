# Maker replay execution addendum — 2026-09-27

**Status: prospective execution choices FROZEN; owner approval and scoring-date confirmation PENDING.**
Owns the remaining execution choices in the [hurdle registration](maker-replay-hurdles-preregistration-2026-09-27.md).
Read with that registration before building its execution manifest. No real 88a, panel, wallet, settlement or
calibration data was opened to choose these rules. This is a method freeze, not an empirical estimate or permission
to read data. The agent-proposed 2026-10-12 America/Toronto look still needs owner confirmation.

## Conservative public-trade hazard

The design's [net screen](../operations/informed-maker-design-2026-09-25.md#quoting-policy-informed_v0-pure-function-testable-offline)
uses `reward_per_minute - hazard_per_minute * 0.0043 * max(posted_leg_sizes) > 0`.
Keep the adverse-loss input **0.0043 pUSD/share** and the strict positive inequality. Public prints bound opportunities
for our counterfactual first fill; they do not establish our queue position, actual fills or a guaranteed loss bound.

Freeze the following estimator before any panel exists:

1. **Window:** exactly seven closed UTC 88a capture dates, **2026-09-20..2026-09-26**, excluding every quote-panel date.
   Use only sealed, hashed public-trade and lifecycle/coverage records and contemporaneous descriptors. No settlement,
   markout, future price, reward, policy result or own-account event enters calibration. Do not extend the window to
   overcome a sparse result. All timestamps below are capture timestamps; a late print belongs to its capture minute.
2. **Denominator:** every complete UTC band-minute `[t,t+60s)` whose captured descriptor at t says local T+1 or T+2,
   for every discovered condition in the calibration window. Require valid trade-stream coverage for the entire minute,
   derived from retained lifecycle evidence with the exporter's 30-second expiry. Exclude gaps, unknown discovery,
   invalid/conflicting trade rows and missing descriptors; an empty trade file alone is not evidence of zero trades.
   Do not filter on price, future settlement, displayed depth, eventual quoting, reward share or observed trade size.
3. **Numerator:** mark that minute 1 if at least one valid public trade in either YES or NO is captured in it, else 0.
   Deduplicate by `(condition_id, trade_id)`; identical duplicates count once, conflicting duplicates invalidate the
   minute. A missing venue ID uses the exporter's frozen content-hash identity. Count both aggressor sides and all
   prices and positive sizes, without testing whether a hypothetical quote would fill. Multiple trades still count 1:
   the engine cancels both legs and the remainder at its first fill. These rules over-admit possible fill events.
4. **Pooling:** pool these Bernoulli observations across bands and dates **within each stable city-market cluster**,
   combining T+1 and T+2. Do not fit individual condition/band hazards. Let `n_m` be complete band-minutes and `x_m`
   occupied band-minutes; report both and the number of contributing dates. Let M be the number of distinct city
   clusters in the union of calibration discovery and the sealed quote-universe inventory (absent cities remain in M).
5. **Exact estimator and quantile:** use the one-sided Clopper-Pearson binomial upper limit at quantile
   `q = 1 - 0.01/M`: `U_m = BetaInverseCDF(q; x_m+1, n_m-x_m)` for `x_m < n_m`; `U_m = 1` when `x_m = n_m`.
   Equivalently U solves `sum_{j=0}^{x_m} C(n_m,j) U^j (1-U)^(n_m-j) = 0.01/M`. This is a Bonferroni 99% family
   upper limit under the working binomial model, not a guarantee under serially dependent or shifting trade flow.
   Use the larger endpoint of a numerical inverse-CDF bracket of width at most `1e-12`, then round upward to
   12 decimal places and cap at 1. No normal approximation, posterior prior or fitted quantile is substituted.
6. **Sparse fallback:** set `U_m = 1.0` if `n_m < 1440`, `x_m < 30`, fewer than three calibration dates contribute,
   or the city is absent from calibration. An empty calibration inventory, unavailable calibration files, or an
   uncomputable numerical bound yields a global **1.0** with an explicit fallback reason; never zero or a pooled
   estimate borrowed from another city. Hash-invalid or changing files refuse the calibration run instead of silently
   dropping them. Retain coverage exclusions and fallback counts, without selecting favourable dates or cities.
7. **Single scalar:** `hazard_per_minute = max_m U_m`, or 1.0 if M is zero. Apply that scalar unchanged to all bands,
   dates and fill bounds in the quote panel. There is no in-panel update, rolling estimate, per-band override or
   search over hazards. A conservative hazard may suppress every quote; that is a result, not grounds to relax it.

The execution manifest records the formula identifier `public_trade_occupied_minute_cp99_max_city`, calibration
source hashes, ordered city inventory, n/x/date counts, exclusions, numeric brackets, fallbacks and final scalar.
The recipe is frozen here; its scalar is necessarily unknown until a separately authorized, bounded calibration read.
Complete and seal that calculation before any scored quote-panel read. Fixture work here does not perform it.

## Every ReplayConfig field

These are execution choices, not values to tune in the manifest. Decimal amounts are pUSD. The base configuration
is passed to `comparison_report`; the only internal replacements allowed are the policy, bound and clock windows
described below. Future fields require a prospective addendum before use.

| Field | Frozen value / derivation |
| --- | --- |
| `policy` | `informed-v0`; comparison also runs `no_quote`, `blind_re1`, `clock_only` |
| `initial_cash` | `100`; initial inventory empty; one shared carried portfolio, never reset daily |
| `band_cap` | `100` |
| `order_cap` | `60` |
| `wallet_cap` | `100` |
| `event_cap` | `100` |
| `factor_cap` | `100`; use captured descriptor loadings, no retrospective factor edits |
| `hazard_per_minute` | Single scalar from the frozen method above; no omitted/None value in a scored manifest |
| `max_book_gap_seconds` | `60` |
| `max_events` | `500000`; input events and combined decision/span ceilings stay binding |
| `fill_bound` | `strictly_through` primary; also run `at_price` sensitivity |
| `clock_pulls` | Empty tuple in the base configuration. Only the existing per-bound `matched_clock` algorithm may replace it: UTC active-interval prefixes, 12 bisection steps, smallest exposure-error trial with first trial retained on ties, one covered-minute tolerance. Preserve its selected windows and aggregate match result. |

The existing RE-1 first-fill/session convention and fixed quoting kernels remain those of the registration's basis.
No change to the event engine, pricing, fair value, caps, fill semantics or net screen is implied by the move endpoint.
Bootstrap settings remain **2000 replicates, seed 20260926**, seed+1 for crossed draws, two-sided 90% percentiles.
Operational ceilings are 64 MiB total bundle input, 100000 records, 300 seconds and 8 MiB output; lowering a ceiling
may only refuse execution, never truncate or select a sample. The manifest binds chosen ceilings before execution.
All sources, universes, active intervals, bundle hashes, executable identities and the computed hazard are exact
bindings supplied later, not discretionary analysis choices. Scoring stays blocked while any binding is incomplete.

## Pull endpoint implementation conventions

The [registration's pull hurdle](maker-replay-hurdles-preregistration-2026-09-27.md#frozen-pull-efficiency-hurdle)
is unchanged. Use the final resting state at t after all capture-time events/decisions at t; between engine events,
carry that state forward to the UTC minute. A HOLD with a resting leg is not pulled; neither leg resting is pulled,
regardless of its reason. A later cancellation cannot earn credit at t. No extra policy tick or future input is added.

Use valid two-sided, noncrossed YES midpoints, in capture order. Starting midpoint age is at most 60 seconds by both
capture and book as-of time; the ending midpoint is the first valid capture at/after t+300 seconds, at most 120 seconds
late and itself no more than 60 seconds old. Require both policies' active book/trade-covered spans from t through that
actual endpoint (including the endpoint); crossing an inactive period, gap or day with no declared exposure excludes
the opportunity. Count overlapping horizons once per band/start minute and cluster by the start's UTC date and city.
Publish exclusion counts and paired per-band/day counts; missing horizons are not non-moves. The common opportunity
set is formed before counting either policy's pulls. It is a move endpoint, independent of settlement-P&L exclusions.

Report aggregate matching and, separately, `abs(informed_pulled - clock_pulled) <= 1` on this common minute set.
Do not search again using the move panel or move labels. Either failed match makes the hurdle UNMATCHED. Both pull
denominators must be positive and the clock's removed-move numerator positive, otherwise UNIDENTIFIED. Informed zero
removed moves with a positive denominator is identified at zero. Sum paired counts inside date/market cells; bootstrap
whole dates and independent date x market multiplicities, then recompute the ratio of summed counts in each draw.
Do not average cell ratios or rematch exposure in a draw. Omit undefined draws, distinguishing empty intersections
from nonempty zero denominators/numerators. Require at least ten dates AND ten markets and 100 valid draws in each
scheme. Report the standard error and descriptive normal 80%-power MDE for the ratio as well as percentile intervals.
Only the primary **point ratio >= 2**, with these gates satisfied, meets the pull hurdle; its lower interval need not
exceed 2. Both bounds are reported. Endpoint success alone cannot issue the combined replay decision.

## Approval binding

The owner signature is an explicit [DECISION_LOG](../operations/DECISION_LOG.md) row containing the raw-byte SHA-256
of the final registration and this addendum. The [verifier contract](../operations/maker-replay-authorization-verifier-design-2026-09-27.md)
defines its machine-readable cells and CLI checks. Do not add an approval row on the owner's behalf. This task
authorizes implementation, fixtures and publication only. Changed frozen bytes invalidate the row; signing and
independent execution-manifest enrollment remain separate from proposing October 12 or updating the draft PR.
