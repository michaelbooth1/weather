# T+1/T+2 weather maker fair-value pre-registration

Frozen specification for handoff 110b. This file is committed before any real
inputs are read. Implementation and verification use synthetic fixtures only.
This is not a model-panel candidate, a promotion request, or an edge claim.

## Inputs and fixed estimator

Use local target-date leads one and two for registered markets. Admit only
records captured at or before the query, with issue time no later than capture.
Select the newest complete retained NBP issue with a unique target maximum:
the parser-v2 00Z-valid token whose 12-hour-prior start and valid instant both
fall on the target local date. Vendor the selector from parser integration
`abd648c7c`; no runtime dependency on that branch. Missing sentinels, ambiguous
slots, unknown station geography, reversed or repeated percentile knots, and
conflicting records at the same issue time are unavailable, never repaired.

Interpolate a CDF through p10/p25/p50/p75/p90. Extend the first and last
segments linearly to probabilities zero and one and clamp beyond those tails.
Integrate integer native-unit bands at half-degree boundaries: lte includes
everything below value+0.5; gte includes everything above value-0.5; bounded
bands include [value-0.5, value_hi+0.5]. Require a complete nonoverlapping event
partition, then renormalise across siblings. NBP mainland values are Fahrenheit;
no unknown-station or unverified Celsius NBP support is implied.

Probability-unit stdev is exactly sqrt(p*(1-p))*(bulletin_age_hours/24+0.25).
An exactly zero/one marginal is Unavailable because contracts v0.1 requires
strictly positive stdev; no hidden epsilon changes this formula.
Expected NBP availability is the 01/07/13/19Z cycle instant plus a fixed one-hour
publication allowance, an engineering assumption, not measured latency.
Expiry is the next such availability after issue, capped at issue+24 hours.
Already expired issues are not revived by a late fetch.

Fallback is only a captured daily_high forecast_high_c row with provider issue
evidence and local issue-date lead one, target matching the requested event.
The legacy _c field is native-unit. Use a Normal CDF with fixed climatological
spread 2 C / 3.6 F. Source: the explicit zero-fit engineering prior in this
pre-registration; it is not an estimated climatological error or a retained
measured finding. This limitation must accompany results. No fitted parameter,
source averaging, T+2 substitution, or market-price input is permitted.
Fallback expires at provider issue+24 hours; use the same age-based probability
stdev. Every fair-value result has calibration_grade="none".

T+0 is separate: read long-row model_probability with matched snapshot identity,
source-row release lineage and explanation sidecar; expose the captured
afternoon_residual_centering context in provenance/model identity. Never
recompute. Expiry is original snapshot capture+15 minutes. Missing release or
stage evidence is unavailable. T+0 is excluded from this scoring protocol.

## Frozen evaluation, after the panel closes

Score once after 2026-10-08 on panel-B-aligned target dates 2026-09-25 through
2026-10-08 inclusive, only against captured 88a T+1/T+2 two-sided mids and
reconciled settlements. No production input is authorized by this document.
First require the production agent's bounded hashed export and verify its
capture/issue/target/settlement identities. Record export hashes and code tip.
Do not replace missing dates, fill gaps, or retrospectively query providers.

Use the first complete captured minute in each UTC hour per event/lead;
compute paired mean band Brier difference (provider minus contemporaneous mid),
then average hours within market-day before equally weighting market-days.
Report lead one and lead two separately, NBP and fallback separately, and a
predefined pooled descriptive table. Expect Brier to be worse than market mid.
Report coverage, exclusions by reason, date clusters, market clusters and
market-days; unavailable estimates never become 0.5 or zero losses.

Reliability uses fixed bins [0,.1), ... [.9,1], reporting count, mean probability,
observed YES frequency and mean declared stdev. Report paired Brier and
reliability uncertainty with 10,000 fixed-seed (110b interpreted as integer 110)
crossed date x market bootstrap replicates: independently resample dates and
markets and multiply their multiplicities. Give two-sided 90% percentile
intervals and date-only sensitivity. Report UNDERPOWERED if either cluster
dimension has fewer than ten unique clusters. No significance/promotion gate,
alpha spend, repeated looks, centre-skew selection, or live authorization.
Report detectable-effect/power limitations; an interval crossing zero is not
evidence of an improvement. Any estimator or scoring change requires a dated
amendment before reading results, never an edit of this frozen specification.

## Clarification 1 — 2026-09-25, handoff 110c (before scoring)

The no-market-input claim applies to the T+1/T+2 NBP and PIT fallback estimators
in this frozen scoring protocol. It is not a blanket claim about served T+0
releases: `market_shrink` calibration can include market prices. The T+0 adapter
now requires the release's calibration method, bound to the same verified release
ID/manifest as the snapshot, records it in `model_id` and `inputs_hash`, and returns
`Unavailable(kind="out_of_scope", reason="market_informed_release")` for
`market_shrink`. Missing or ambiguous method evidence remains unavailable; do not
assume identity. The bounded export must supply `release_calibration_method` on
each matching source row from that release's probability-calibration artifact
(`market_bin.method`); this is an export projection, not an existing capture field.
No artifact, release, or production row was read to make this clarification.

The additive pre-tag contract now represents an exactly decided marginal with
`stdev=0` when p is 0 or 1. The frozen stdev formula is unchanged; these cases no
longer require `Unavailable`, and no epsilon is introduced. Weather descriptors
declare `group_relation="partition"`. Scheduled METAR pulls retain the -3/+10
minute window; scheduled model events expire at issue/availability +10 minutes,
detected bulletin arrivals at fetch +10 minutes. New-high pulls retain their
existing lifetime pending fresh evidence; determined-band vetoes remain permanent. Core safety and
freshness checks still govern re-entry. These are fixture-verified interface and
clock repairs, not a scored estimator change, new panel, or live authority.
