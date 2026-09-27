# Maker replay hurdles — frozen pre-registration, 2026-09-27

**Status: FROZEN analysis and hurdle specification; owner signature PENDING. No scoring authorization.**
Owns the first informed-maker replay decision, its fixed panel, endpoints and reporting rules.
Read before any scored 88a comparison. Execution admission belongs to the
[bundle contract](../operations/maker-replay-bundle.md); the proposed signature check is in the
[verifier design note](../operations/maker-replay-authorization-verifier-design-2026-09-27.md).
This is a prospective protocol, not a result or a live-trading approval.

## Freeze and scoring date

The design basis is [Evaluation harness](../operations/informed-maker-design-2026-09-25.md#evaluation-harness-maker_corereplay)
and the [110l report](../roadmap/agent-report-2026-09-110l-maker-replay-harness.md), read at harness commit
`8ee7b8ad34c3d6ab8c073e93f90fc717586505ca` on `origin/codex/maker-replay-harness-20260926`.
The owner selected **2026-10-12** as the scoring date in the task requesting this document.
There is one scheduled scored look on that America/Toronto date, after the input seal and authorization checks.
No interim economics, policy comparison, confidence interval or move-efficiency result may be inspected.
Envelope, hash and coverage diagnostics are permitted; they cannot choose policy settings or a favourable subset.

The quote panel is **2026-09-27 through 2026-10-10 inclusive: 14 closed UTC 88a capture dates**.
These are capture dates, not settlement target dates or the similarly numbered historical research mission.
The additional **2026-10-11 UTC** bundle may supply settlement evidence only: all its active intervals must be empty,
and it contributes no quote minutes, band-days or date clusters. It cannot repair an earlier capture gap.
Unresolved T+2 inventory can still prevent scoring; a calendar allowance is not proof of settlement completeness.
If the prerequisites are not satisfied on October 12, record BLOCKED or UNDERPOWERED as appropriate; do not extend
the panel, replace dates, move the look, relax a hurdle or repeatedly score until it passes. A successor needs a new
dated, owner-signed prospective registration, with every previous read disclosed. Preserve this file unchanged.

The [reserved-window status](../operations/reserved-confirmation-window.md) was NONE RESERVED when this was written.
Recheck it before input access; this protocol neither consumes model-panel alpha nor authorizes access to a later reservation.
No real bundle, settlement outcome or replay score was read to write this registration.

## Population and countability

Use International Polymarket weather conditions discovered in sealed 88a segments for the registered capture dates,
with stable city-market cluster identities. Retain every discovered band in the signed universe inventory; no selection
by future settlement, fill, reward or move. The exact sorted market and condition lists, declared active intervals,
bundle/stream hashes, plugin inputs and settlement sources must be sealed before the scored look.
The inventory must distinguish absent discovery from an observed, legitimately unquoted band.

- Admission requires **at least 14 closed 88a dates**. This first panel has exactly 14 possible quote dates; the
  settlement-only bundle does not count toward that minimum.
- Each primary paired contrast must retain **at least 10 distinct date clusters and at least 10 distinct market
  clusters** after exclusions. Bands, tokens, fills and repeated ledger rows are not independent clusters.
- Preserve capture-time ordering, source hashes, native units, captured served T+0 probabilities and plugin validity
  cutoffs. Recomputing historical serving output or importing later information is prohibited.
- Missing/expired book or trade-stream coverage, unbound terms, malformed inputs and unresolved settlements are
  exclusions, never zero profit or zero fills. Use reconciled settlement-ledger facts; no CSV/proxy fallback.
- Apply the harness's whole-cell rule: an incomplete or unpaired band removes its complete market/UTC-date cell from
  that contrast. Publish the excluded cells and reasons, all input dates and the effective cluster counts separately.
  A no-quote zero is valid only on an otherwise admitted comparison cell.

## Policies, fills and accounting

The candidate is **informed_v0** (the exact CLI/profile spelling is **informed-v0**). Comparators are **blind_re1**,
**no_quote**, and **clock_only**, all on identical captured inputs and the same starting portfolio/cap assumptions.
Pin the policy, plugin, engine and scorer source identities in the execution manifest. The registered policy semantics
are those of the harness basis above; a behavior change needs a prospective amendment, not silent use of a new branch tip.
Blind RE-1 retains its documented first-fill/session behavior and shared carried cash/inventory. It is not retuned to
resemble the informed policy. The clock control uses the harness's exposure-only prefix-window matching, separately
for each fill bound, with the existing one-covered-minute tolerance and bounded duration search. An UNMATCHED control
cannot satisfy the pull hurdle. Do not optimize its schedule using moves, rewards or returns.

Report **both fill bounds**, always: **strictly_through** is the conservative primary; **at_price** is sensitivity.
These bound the price predicate, not realized P&L: fewer fills need not mean lower profit. They do not identify queue
position, aggressor selection, invisible cancels or latency. Preserve the sibling/remainder cancellation convention and
the report's `RE1_TRANSPORT_ASSUMED` limitation. A sensitivity result cannot rescue a failed primary result.

For each policy and band/UTC-day report the existing `modeled_net_k1` and `modeled_net_k05` metrics:

`modeled net(k) = k * modeled reward accrual + nominal maker rebate + settled inventory P&L`.

**k = 1.0 is primary; k = 0.5 is the mandatory sensitivity.** Use contemporaneous captured reward terms and the
scorer's disclosed rebate convention. Modelled rewards and nominal rebates are not paid cash and never replenish
replay buying power. Maker fees, purchase costs and settlement payouts follow the frozen scorer; no taker liquidation
is invented. Markouts at 1/5/30 minutes and settlement are alternative valuations, not extra settlement P&L.
Report missing markouts, unresolved fills, cash-hours, pull fraction, requotes, and fills inside/outside event windows.
Operating costs and payment reconciliation are outside these modelled-net fields: passing them is not proof of
after-all-cost profitability. The [item 330 accounting identity](../roadmap/items/item-330-maker-economics-refocus-master-plan.md)
and authoritative wallet cash remain necessary for that separate claim.

## Frozen statistical decision

Show band-day scores; for inference, sum paired band-day differences within each complete market/UTC-date cell and
take the equal-weight mean across those cells. This is the harness estimand, **mean paired total modelled net per
complete market/UTC-day**; do not relabel it as mean per band-day or weight cities by their number of trades.

Use **2,000 bootstrap replicates**, base seed **20260926**, and the harness's **two-sided 90% percentile intervals**
(5th and 95th percentiles). Date bootstrap resamples whole dates; crossed **date x market** bootstrap independently
resamples dates and markets with multiplicity. Use the existing seed-plus-one convention for crossed resampling.
Report both schemes, valid and empty replicates, sample counts, bootstrap standard error and the descriptive
80%-power normal-approximation MDE. Ten clusters is a minimum, not proof of power. Fewer than 100 valid replicates,
missing intervals or fewer than 10 clusters on either required axis makes the decision UNDERPOWERED.
No IID band or market-day resampling may replace crossed inference.

The economic hurdle passes only if **all four lower bounds are strictly above zero**, using **strictly_through,
k = 1.0**: informed_v0 minus blind_re1 and informed_v0 minus no_quote, each under date and crossed date x market
inference. Thus the conservative lower bound must beat **both** baselines, not merely the candidate's point estimate.
Equality at zero fails. This is one conjunction of predeclared hurdles, not permission to select the most favourable
baseline, clustering scheme or fill assumption. Report every contrast at k = 0.5 and under at_price, including sign
changes; they are robustness diagnostics without a second opportunity to declare success.

## Frozen pull-efficiency hurdle

Define a large move before observing outcomes: **an absolute YES two-sided midpoint change of at least 0.05 pUSD
over five minutes**. At each UTC minute t in a declared active interval, use the latest valid captured midpoint at or
before t (at most 60 seconds old), and the first valid midpoint at/after t+5 minutes (at most 120 seconds late).
Both policies must have covered book/trade evidence throughout the interval. Missing endpoints or gaps exclude it.
Count one band-minute opportunity, not a separate YES and NO observation; overlapping five-minute horizons remain
clustered. This endpoint measures avoidance of price moves, not proven adverse selection or avoided account losses.

On that common opportunity set, a pulled minute is one with neither leg resting immediately after the decision at t.
The decision uses only inputs captured through t; later decisions cannot retrospectively earn pull credit. Count a
large move as removed by a policy only when that policy was pulled at its starting minute. For policy p define
`E_p = large-move opportunities removed / pulled minute opportunities`. Report both counts, their common denominator,
each efficiency, and `E_informed / E_clock`. Require matched exposure on this endpoint's common set too: the sampled
pull counts must differ by at most one minute. The existing aggregate exposure match alone cannot prove this.

The hurdle is **pull efficiency >= 2x the clock-only baseline** under strictly_through. Both policies must have
positive pulled-minute denominators and the clock must remove at least one large move. A zero denominator or zero
clock numerator is UNIDENTIFIED, never an infinite ratio or an automatic pass. Report paired date and crossed
date x market 90% bootstrap intervals for the ratio using the same settings, recomputing ratios of summed counts
within each replicate; omit undefined draws and report their count. The >= 10 cluster and >= 100 valid-replicate
rules apply here too. The **point ratio >= 2.0** is the frozen pull hurdle; its interval is mandatory uncertainty
disclosure, not an unregistered lower-bound >= 2 rule. Report at_price sensitivity without changing the decision.
The basis harness does not yet implement this endpoint: absence must block the combined decision, not count as PASS.

## Result and execution boundary

Report the economic and pull hurdles separately. A **REPLAY_HURDLES_MET** conclusion requires both, all admission
minimums, a valid owner authorization and every mandatory sensitivity/report field. Otherwise report the exact
BLOCKED, UNDERPOWERED, UNIDENTIFIED, UNMATCHED or HURDLE_NOT_MET reason; retain estimates with their limitations.
An interval containing zero means the delta is not distinguishable from zero at this registered interval level.
Do not refit, select a hazard or alter cash/caps after seeing this panel's outcomes.

Before any scored read, a separately reviewed execution manifest must freeze every `ReplayConfig` field (including
the conservative `hazard_per_minute` input), exact policies/config/source hashes, all inputs and the definitions above.
An omitted hazard is not zero: the basis informed policy refuses quoting when that bound is absent. This hurdle
registration supplies no empirical hazard estimate. Missing run bindings require an owner-approved prospective
completion before scoring; changing a frozen policy or analysis choice requires a new registration. Signing a vague
or incomplete manifest is insufficient. This Markdown file is not the JSON artifact accepted by the current CLI.

The [110l qualification limit](../roadmap/agent-report-2026-09-110l-maker-replay-harness.md#re-1-behavior-port--2026-09-27-continuation-from-0bd7adf98)
remains explicit: recorded minute parity does not establish full-session/transport parity. Even a replay hurdle pass
does not discharge the design's T+1 fair-value reliability table, at least seven days of forward shadow/replay agreement,
operational drills, accounting reconciliation or the owner's separate decision to start live trading.

## Owner-signature block — unsigned; complete by detached attestation

| Binding | Owner attestation |
| --- | --- |
| Owner name / independently trusted signing-key ID | PENDING |
| Decision | PENDING — approve one offline scored look only |
| Frozen protocol | This repository path, introducing commit and raw-byte SHA-256: PENDING |
| Execution manifest | Path and raw-byte SHA-256, including complete run bindings: PENDING |
| Approved scoring date | 2026-10-12 America/Toronto; no earlier scored read |
| Quote dates / settlement-only date | 2026-09-27..2026-10-10 UTC / 2026-10-11 UTC |
| Owner signed_at / authorization expiry (UTC) | PENDING |
| Review approval reference / detached signature | PENDING |
| Pre-score attestation | PENDING — criteria/config frozen before any scored read; all prior access disclosed |

Do not insert a simulated owner signature or treat task approval to write/push these docs as signing. A detached
attestation binds the final committed bytes and avoids a self-referential hash. Keep this frozen file and attach the
completed attestation separately. No hash enrollment, key enrollment or scoring is authorized by this change.
