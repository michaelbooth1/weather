# Profit-edge information preregistration — authoritative print freshness

Status: **FROZEN BEFORE MODEL WORK**

Frozen at: `2026-07-26T15:05:43Z`

Code identity at freeze: `ced7308e1f233fc69fe86b8dfce34b328a52e2fd`

No model, feature implementation, fit, tuning pass, threshold search, or
confirmation-window outcome inspection preceded this document. This is a
preregistration, not an authorization to promote or trade.

## Why this candidate survived the diagnosis

The frozen hour-20 trace uses the same repaired, settled corpus as the accepted
skill-gap decomposition. At the earliest canonical market-local hour-20
capture, the pooled artifact receives `high_so_far`, `current_temp`, and
`live_reading_temp` in all 124 market-days. The day's trajectory is therefore
not globally omitted.

The unresolved distinction is authority and freshness:

- the printed floor already identifies the eventual winning band in 86 of 124
  market-days, but the settlement band is still above it in 38;
- every selected source-health group reports at least one failed source, and
  114 of 124 specifically report failed `weather_forecast`, `wu_current`, and
  `wu_history`;
- no current maximum is trusted: 69 are support-only, 15 quarantined, and 40
  missing;
- neither support-only nor quarantined maxima exceed the printed high in this
  cut, so merely taking a larger captured maximum is not the candidate;
- the hour-20 artifact contains the printed high and trajectory features, but
  not an exact age for the last accepted Weather Underground history print.

Separately, the diagnosis found a correctness bug: incumbent blending occurs
after the printed-high hard floor and can restore mass below that floor. That
bug is not this information candidate and its correction may not be credited
as candidate uplift.

## Frozen candidate

Candidate id: `authoritative_wu_print_freshness_v0.1`

The candidate is a point-in-time feature family derived only from captured
Weather Underground history and captured source diagnostics:

1. `wu_history_print_age_minutes`: capture time minus the observation time of
   the latest accepted WU history row used by `high_so_far`;
2. `wu_history_success_age_minutes`: capture time minus the most recent
   successful WU-history acquisition represented in the captured record;
3. `wu_history_authority_state`: one of `fresh`, `stale`, `failed`, or
   `missing`, with missing or malformed diagnostics failing closed;
4. a missingness indicator for each numeric age.

No final-day summary, settlement value, future WU row, market price, market
outcome, or post-capture source response may contribute to these values.
`hours_at_peak` and the existing current-max disposition flags remain baseline
features; they are not relabelled as new information.

## Hypothesis and causal mechanism

At target-local hour 20, a printed high with a recent successful authoritative
WU print should support late lock-in. The same numeric high paired with a
failed, missing, or old authoritative print should retain more uncertainty
above the printed floor. The feature family should therefore distinguish
"the day is genuinely locked" from "the last authoritative print is not fresh
enough to prove lock" without learning the settlement label.

This is a **loss-avoidance** hypothesis. Mission 1 found no historically
exploitable subset under the frozen trading rule, so even a successful result
would not establish profit, execution quality, or deployment readiness.

## Frozen cuts and comparators

The comparison is paired on identical captured partitions:

- artifact family: built-in F markets only;
- primary cut: earliest target-market-local hour-20 partition for each
  market/day;
- secondary loss-avoidance cut: earliest partitions at hours 18 through 23,
  reported separately for near-resolved and non-near-resolved market states;
- primary-objective guardrail: hours 09 through 14;
- comparator: the then-frozen pooled baseline with the same training corpus,
  hyperparameters, postprocessing, and incumbent policy.

Before either arm is scored, the post-blend printed-floor correctness defect
must be handled identically in both arms. Its standalone delta must be reported
separately. The information candidate cannot claim that mechanical repair as
uplift.

## Untouched confirmation window

The confirmation panel is the first 14 complete eligible target dates beginning
`2026-07-27`. A date is complete only when every otherwise-countable built-in F
market has its canonical captured partition and independently settled label.
Incomplete dates remain visible in coverage but do not shift a later date into
the panel after any outcome metric has been opened.

The full ordered date list, captured-input hashes, code identity, artifact
identity, and arm identities must be frozen before any outcome-bearing score is
read. No sequential peeking is allowed. If any confirmation outcome or
outcome-derived aggregate is inspected before that freeze, the panel is spent
and a later untouched window must be preregistered.

## Frozen success rule

All of the following are required:

1. candidate probability mass is within `1e-9` of one for every complete
   partition, with no positive mass above `1e-9` in a band made impossible by
   the point-in-time printed floor;
2. primary hour-20 equal-market-day categorical Brier improves by at least
   `0.003` absolute and the paired target-date-block 95% confidence interval
   for candidate-minus-baseline Brier has an upper bound below zero;
3. mean hour-20 winning-band mass improves by at least `0.03`;
4. hour-20 categorical log loss does not regress;
5. the 09:00–14:00 guardrail does not regress by more than `0.001` absolute
   Brier overall or by more than `0.003` in any adequately populated market;
6. no large result is accepted until a leakage audit proves every candidate
   value was available at or before its capture instant.

Results are reported with equal market-day weighting, target-date-block
resampling, leave-one-date-out sensitivity, per-market rows, and explicit
coverage. Sparse or failed-source strata may explain a result but may not
replace the frozen primary rule.

## Leakage and invalidation rules

The candidate is invalid if any value is reconstructed from a future tape row,
the daily settlement summary, an eventual winning band, a mutable current
source query, or a file written after the scored capture. Observation
timestamps must be present and not later than capture; malformed or missing
timestamps fail closed to missing. Backfilled history may be used only when
the original captured record proves it was already available at that instant.

A surprisingly large improvement is a leakage suspect first. Replay identity
must cover the feature extractor, captured inputs, artifact, postprocessing,
and label join. Prediction must complete before settlement labels cross the
scoring boundary.

## Explicitly not done

- No feature or model implementation.
- No fitting, tuning, threshold search, or ablation.
- No confirmation-window collection or outcome evaluation.
- No fix for the post-blend floor-ordering bug.
- No promotion, release, pointer, activation, serving, scheduler, collector,
  sizing, trading, pull request, merge, or master push.
- No claim that this candidate can create tradeable edge.
