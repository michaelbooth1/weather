# Agent Report - 2026-07-22 Workstation Taker Bakeoff

## Outcome

**STOP: no positive after-cost edge survived.** The frozen offline bakeoff has
20 complete, settled/countable primary fleet dates. None of nine preregistered
policies has positive mean net P&L with a strictly positive fleet-date
bootstrap interval, and none beats the raw control with such an interval.
Therefore the predeclared rule forbids a threshold or sizing sweep.

All realized fills occur on one market-day, Denver 2026-07-19, and every fill
loses. The least-negative filled policy is the low-price tail cap at
`-$0.3669` over two fills. The current-high lock-in arm loses nothing only
because it never fills.

## Frozen inputs and countability

- Input: read-only 2026-07-22 workstation mirror.
- Frozen run folders: 32, covering 2026-06-18 through 2026-07-19.
- Replayed: 31; the 2026-07-16 orders tape is header-only and fails closed.
- Complete 12-market and fully settled/countable primary dates: 20.
- Excluded dates: 12, primarily because labels are not fully
  settled/countable; no partial date contributes to the primary result.
- Frozen-manifest canonical hash:
  `8d37af96729e7afd9fbffd2aa21453f0ea13bdc067f354198f0b8eb2cfe60997`.
- Manifest file SHA-256:
  `3DBC23343EE1187AE73FEEA6BED44677C5FB2E8429887D500C644EFF4B719A50`.
- Input-audit SHA-256:
  `90F43A445B4DEE8C84B8EEF569AE3679A7E6BDFCA0872678A6CBD7FC23CE9327`.

Every orders tape, settlement label, and exchange-economics input is hashed.
Exchange-economics gates remain `BLOCK`; fixed modeled costs are still applied,
but all results remain research-only.

## Design

The permission fence is disabled only inside the offline counterfactual. Nine
fixed arms cover raw and calibrated edge, low-price tail caps, overpriced-band
fades, winner/adjacent filters, current-high lock-in, late-day liquidity,
strict-edge, and small-order behavior. Both YES and NO opportunity funnels are
recorded; `fade_overpriced` is the only policy with an explicit NO evaluation
surface.

The primary inferential unit is the entire fleet date. Confidence intervals
use 10,000 deterministic date-cluster bootstrap samples. A chronological 60/40
development/confirmation split is reported as robustness only: policies were
preregistered, so neither segment is used to tune them.

Large daily rows are folded through a SQLite scratch store and compact
projections. Each day is checkpointed and resumable; canonical mirror tapes
are never rewritten.

## Primary results

| Policy | Fills | Net USDC | Mean per fleet date | 95% CI | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| raw edge control | 9 | -15.6585 | -0.7829 | `[-2.349,0.000]` | 9/9 losses |
| calibrated edge | 2 | -3.3476 | -0.1674 | `[-0.502,0.000]` | 2/2 losses |
| low-price tail capped | 2 | -0.3669 | -0.0183 | `[-0.055,0.000]` | 2/2 losses |
| fade overpriced | 2 | -0.7337 | -0.0367 | `[-0.110,0.000]` | 2/2 losses |
| winner centered / adjacent | 2 | -7.2845 | -0.3642 | `[-1.093,0.000]` | 2/2 losses |
| current-high lock-in | 0 | 0.0000 | 0.0000 | `[0.000,0.000]` | no evidence |
| late-day liquidity filtered | 2 | -7.2845 | -0.3642 | `[-1.093,0.000]` | 2/2 losses |
| strict edge probe | 8 | -14.6271 | -0.7314 | `[-2.194,0.000]` | 8/8 losses |
| small-order probe | 9 | -1.5671 | -0.0784 | `[-0.235,0.000]` | 9/9 losses |

The first 12 chronological primary dates produce zero fills for every arm. The
eight-date confirmation segment contains the single losing Denver date. The
four high-capture-coverage dates also produce zero fills. Thus the negative
result is sparse, but there is no hidden positive segment.

## Bounded Denver loss casebook

The finalized filled-order casebook captures all 36 strategy-level fills with
no overflow. Those 36 rows collapse to only nine distinct captured opinions:
every one is a `served_current` Denver YES buy on 2026-07-19 at a `$0.001`
ask, in either the `94-95 F` or `96-97 F` low-price tail. The overlapping
strategies repeatedly express the same captured opinions at different sizing
caps; this is not 36 independent observations. There are no NO fills.

All nine captured opinions lose because Denver settles at `98 F`, in the
`98-99 F` winning band. Importantly, the recorded market modal is already
`98-99 F`: the directional/modal forecast is correct while the served
distribution still leaves excessive mass on cooler adjacent tails. Across the
nine raw-control fills, raw fair probability on the losing bands ranges from
`0.076819` to `0.266728`; calibrated fair ranges from `0.047395` to
`0.202435`, and the actual after-cost entry EV ranges from `0.046345` to
`0.201385` per share. Reliability-adjusted fair ranges from `0.052557` to
`0.181695`, but the raw control does not require that lower probability to
govern entry.

This localizes the single realized loss cluster to distribution
under-sharpness/tail-mass leakage rather than a wrong modal Tmax forecast. It
also explains why `current_high_lockin` avoids the loss while the
winner-centered-or-adjacent arm does not: exact lock-in makes no trade, whereas
the adjacent allowance admits the losing cool tails. The evidence supports the
separate ordinal-smoothing/stage-attribution research line; it does not justify
post-hoc taker threshold fitting on this one date.

Casebook:
`scratch/workstation-research-output/workstream_b/taker/full/filled_order_casebook.csv`,
SHA-256
`5A5813E464D10F24BACE6EEADC20C6889C0988B9C572E3A1AF88B37FAC155EEA`.

## YES/NO funnel

The YES control evaluates 502,851 priced rows, 193,206 with positive raw edge,
and 1,068 with positive modeled after-cost EV, yet only nine pass every
entry/risk/execution gate; all nine lose.

The NO fade evaluates 56,408 priced rows, including 31,487 positive-raw-edge
and 16,264 positive-after-cost-EV rows, but has zero buy actions and zero
fills. The main mutually exclusive rejection reasons are market-centered warm
tail, after-cost EV too small, adverse-selection cap, zero sizing, early-hour
source state, risk-adjusted edge, and missing ask size. Positive theoretical EV
is therefore not being confused with an executable opportunity.

## Evidence limitations

- Nineteen of 20 primary dates have no fill under any arm.
- Only four primary dates meet the strict high-capture-coverage sensitivity
  threshold; the remaining 16 form a moderate-coverage diagnostic.
- Exchange economics are blocked, so the modeled cost layer is not a proof of
  actual fee/rebate economics.
- A zero-fill arm is not a profitable arm.
- The permission-off result is counterfactual research and does not authorize
  a live permission change.

## Artifact and disposition

The research CLI now requires the immutable data root explicitly for every
command. Its shared output-path contract resolves existing symlinks and
junctions and rejects any direct or aliased output below that root; it no
longer relies on a directory literally being named `data`. The combined maker,
taker, and shared-path guard suites passed all 15 focused tests.

Primary output:
`scratch/workstation-research-output/workstream_b/taker/full/aggregate.json`,
SHA-256
`8ACB465D142A28344C74FC651922F703A74D3256615A24452D026458440EAB8E`.
This is the final aggregate regenerated at 2026-07-22 11:10 local after the
bounded casebook fields were added.

Stop this policy-search line on the present tapes. Do not optimize thresholds
or sizing around the one losing date. The next useful taker experiment requires
new complete, high-coverage, settled fleet dates and valid exchange economics;
model-skill work has higher expected value in the meantime.
