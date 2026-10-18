# informed-v1 candidate frontier — preregistration DRAFT, 2026-10-16

**Status: UNSIGNED DRAFT.** This document grants no authority: no live, shadow or scoring authority, and no
panel read. A scored read is impossible in code until all of these happen:
the owner signs the margin (§4a) and this document; a reviewed change pins its SHA-256 in
`maker_core.frontier.prereg.SIGNED_PREREGISTRATION_SHA256`; the grid hash, decay digest, fill model binding,
decision rule digest and toxicity table digest below still equal what the run uses; and the code clock
reaches 2026-11-14T00:00Z. A scored run must cover all 120 points and all 3 baselines. The
design notes are under item 330 (builds 3 and 4). **Read when:** reviewing, amending or signing the informed-v1 frontier read.

## 1. Question and hypotheses

The question is which quoting rules on the informed-v1 grid earn the most liquidity reward per band-day,
net of the modelled adverse cost and of other makers' response to our quote, compared with not quoting,
the RE-1 blind quote and informed-v0.

- **H1 (reward).** For each grid point, the reward under the `central` competitor-response bound is
  reported with the `none` and `full` bounds around it. A point "earns more reward than a baseline" only
  if its `full`-bound reward exceeds that baseline's `none`-bound reward. This is the dominance rule: it
  holds under every response assumption.
- **H2 (net, the decision metric).** Each point's net modelled P&L is reward minus the modelled adverse
  cost (filled shares × the fill-cost provider's markout, never below 0.0043) minus, for `resting_sell`
  points only, an exit fee bound per filled share (§4a). It is reported under all three bounds, and the central bound decides (§4a). Realised
  settlement and resting-sell P&L are reported beside it. The decision rule selects a candidate for shadow
  quoting; it makes **no net-P&L sign claim** about live trading (§6).
- **H3 (inventory).** For each (width, size, band rule), compare `resting_sell` against
  `hold_to_settlement` on filled shares, exit P&L and held-to-settlement shares. This is descriptive.

There is no centre-skew hypothesis. Skewing the centre toward the model was retracted (established
findings §1b). Every point quotes symmetrically about the size-qualified mid, and the fair value may only
gate a band (`depth_share_fv`).

## 2. The frozen grid

Grid hash: `17b85a248542c45a886228a25f63dce78bf150f7ad5d5fc12e09d5e7643bd457`

That is SHA-256 over the canonical JSON manifest (`maker_core.frontier.grid.manifest()`), whose format is
`maker-core.frontier-grid.informed-v1.0`. The manifest holds the axes, the fixed rules, the baselines and
the sorted points. The hash does not depend on the order in which values are supplied.

| Axis | Values |
| --- | --- |
| Width from the size-qualified centre (cents) | 1.0, 1.5, 2.0, 2.5, 3.0 |
| Size per leg (shares) | 20, 30, 50, 75 |
| Band rule | `depth_only`; `depth_share` (instantaneous no-reaction share in [0.15, 0.70]); `depth_share_fv` (also a valid fair value within one stdev of the mid) |
| Inventory | `hold_to_settlement`; `resting_sell` (filled shares offered at entry + 2 × width, remainder held) |

That gives 5 × 4 × 3 × 2 = **120 points**.

Fixed for every point:

- YES and NO BUY legs of equal size, with no skew;
- horizons T+1 and T+2 only;
- mid in [0.2, 0.8], and no quoting in the last 3 hours before close;
- displayed depth of at least max(75, size) on each side within the max spread;
- the touch buffer;
- per-leg cash at most 60 and per-band cash at most 100;
- an active decided ≥ 0.5 or `pull` event stops quoting;
- the first fill ends quoting on that band-day;
- a quote is held until the next book and for no more than 120 s without one.

## 3. Baselines

The baselines run on the same instants as the grid:

- `no-quote`: zero reward and zero cost;
- `blind_re1`: the frozen `policy.decide` RE-1 profile, one band at a time;
- `informed-v0`: the frozen `policy.decide` informed profile, with the same hazard and fill-cost inputs.

Baselines are re-proposed at every book with no existing legs, and the first fill ends their band-day too.
They are comparison anchors inside one harness, not re-runs of the v2 engine's verdicts.

## 4. Measurement

All measurement comes from one offline pass of `maker_core.frontier.runner.run` over sealed neutral bundles.

- **Reward.** At each book arrival a strategy proposes legs. Reward accrues at rate/86400 per quoted second
  times the share. The share is own Q / (own Q + competing Q in the replayed book + x(a) × own Q), where
  x(a) comes from the competitor-response model (§5) and a is the age of the band's quoting spell.
- **Fills.** Fills come from the injected fill model. The scored read uses exactly one fill model, bound
  on the line below; the code refuses any other. It is build 1's queue-position kernel
  `maker_core.replay.fill_v3` (`fill-v3.0`, `strictly_through` print rule) through the frontier's
  `QueueFillModel` adapter (`maker_core.frontier.adapters.fill_v3_model`). The binding is the adapter's
  module and class qualname, its version, the kernel module and version, and the declared name, so a model
  that only claims a name cannot match (build 4). The v2 price-path predicate is a descriptive bracket in
  `calibrate` only.

Fill model: `maker_core.frontier.seams.QueueFillModel@queue-adapter.1+maker_core.replay.fill_v3@fill-v3.0:v3-queue`

- **Adverse cost.** The adverse cost per filled share is max(0.0043, the provider's markout upper bound).
  A provider veto (`BURST`, `SWEEP`) suppresses the quote (`cancel`; widening is not modelled). The provider
  is build 2's `TableFillCostProvider` over the toxicity table, through the recording adapter
  (`maker_core.frontier.adapters.RecordingFillCost`), which checks the table version and digest and records
  every decision's status, veto and action. Its contexts come from the counterfactual tape's `cf_minutes`
  rows (`strictly_through` backlog) for the panel days. Decisions with no provider markout are counted
  (`cost_unavailable`) and the provider type is recorded.
- **The table is bound.** `score` requires `--toxicity-table`, `--toxicity-table-digest` and `--cf-tape`.
  A scored run refuses the constant stand-in or no provider. The table digest must equal the line below,
  which the owner fills with the chosen table's `TableFillCostProvider` digest before signing. While it is
  not a 64-hex digest, no scored read can match it.

Toxicity table: `UNSET (owner binds the toxicity table digest before signing)`
- **Inventory P&L.**
  - Held shares settle on the captured settlement fact.
  - A resting-sell fill is booked as the locked pair value, 1 − entry − complement price.
  - Shares with no settlement in the bundle are counted, not valued.

## 4a. Decision rule (`maker_core.frontier.decision`)

Decision rule digest: `87de64bd51992826b4b631934a75e51c6aec514c58483c79aaf00035ebfd6d03`

That is the digest of `decision.PROPOSED_RULE.spec()` (format `maker-core.frontier-decision.2`, revised in
review round 4), which holds every parameter below. The margin is unset in it. Signing the margin changes the rule and its digest, and
this line must then be recomputed. The code refuses a scored run whose rule digest differs from the line
above, and `score` refuses while the margin is unset.

- **Net.** For each strategy and capture day: reward − adverse cost − exit fee × filled shares, in pUSD,
  under the `central` bound (`none` and `full` are reported beside it).
- **Exit fee.** 0.0125 pUSD per filled share, the weather taker fee 0.05·p(1−p) at its maximum (p = 0.5),
  an upper bound on flattening a fill as a taker. Makers pay no fee (established findings §10o).
  - It is charged on **`resting_sell` points only**. `hold_to_settlement` points and the baselines hold, so
    they pay none.
  - It is conservative for a point's **own** net. It is **not** conservative for a paired difference
    against a baseline: a lower fee would raise a `resting_sell` point's delta.
- **Primary unit (decides).** Mean net pUSD per capture day, which is the total net over the panel divided
  by its days. It is pooled across every band quoted that day, so it is not a per-band figure. Thin
  quoting earns little in total, so this unit does not reward sparse quoting. `no-quote` is 0.
- **Reported only.** Net cents per quoted minute. It is shown as "none", not 0, for a strategy that never
  quoted.
- **Eligibility floor.** A point must quote at least 60 minutes per capture day on average over the
  panel (`min_quoted_minutes_per_cluster`). Below that it cannot win, whatever its statistic.
- **Clusters.** One per UTC **capture day**. Bands at horizon 1 (event T) and horizon 2 (event T+1) are
  quoted on the same day; clustering on the capture day keeps those correlated quotes together, and
  every cluster is a fully observed day. The report discloses kept and dropped bands per day and horizon.
- **Statistic.** A paired cluster bootstrap with B = 9999 resamples, drawn by `random.Random(20261114)`
  and shared by every strategy.
  - For point j and each baseline k, delta_jk is the difference in the primary unit, and se_jk is the
    bootstrap SD of delta*_jk.
  - **Observed: T_j = min over k of delta_jk / se_jk** (intersection-union): a point must beat every
    baseline. No best baseline is re-chosen per resample.
  - **Null row: T*_j = max over k of (delta*_jk − mean delta*_jk) / se_jk.** Each pair is centred on its
    bootstrap mean.
    - Under intersection-union, the least-favourable null is one pair at the null while the others are far
      positive. The observed minimum is then that pair's statistic.
    - The maximum over pairs of the centred draws bounds that pair's null tail, so max over j of max over k
      bounds every configuration.
    - The minimum, used in round 3, sits below a single pair's quantile and over-rejects. In a seeded
      simulation with one null pair and two far-positive pairs (K = 12, B = 199, 400 datasets, α = 0.05) it
      rejected 19% of the time; the maximum rejected 6.5%, the small-K bootstrap's own slack.
    - Westfall–Young, the marginal p-values and Holm all use this null row.
  - T is a bootstrap-scaled, centred statistic, and its p-values are bootstrap tail frequencies. It is
    **not** a studentized (pivotal) bootstrap. A pair whose bootstrap SD is at most 1e-12 contributes 0.
- **Serial dependence (disclosed; sensitivity only).** Capture days are serially dependent: a band is quoted
  on two consecutive days (horizons 2 then 1), and weather regimes persist. The i.i.d. day bootstrap
  therefore understates the variance somewhat.
  - A pre-declared moving-block bootstrap is reported beside every point: blocks of 2 consecutive capture
    days (`sensitivity_block_length`), with the same statistic and null row.
    - "Consecutive" means consecutive **observed** clusters in date order. A missing capture day therefore
      puts its two neighbours in one block.
    - Block starts are drawn uniformly, so the first and last clusters sit in fewer blocks and are
      **under-weighted**.
  - It **never decides**. The verdict reads only the i.i.d. bootstrap. A Westfall–Young p that passes there
    but not under blocks is disclosed as fragile to serial dependence.
- **Family-wise control (decides).** Westfall–Young step-down max-T, one-sided, over all 120 points, at
  α = 0.05.
- **Holm (sensitivity only).** Holm-adjusted marginal bootstrap p-values are reported beside the
  Westfall–Young values and never decide.
- **WINNER.** Among eligible points meeting all three conditions below, the one with the largest net per
  capture day (equivalently, total net):
  - its Westfall–Young p ≤ 0.05;
  - its smallest delta over the three baselines ≥ the margin;
  - its own net under the `full` competitor-response bound ≥ 0.

  It also needs at least 10 capture days. Otherwise the verdict is **NO_GO**, which is the default.
- **Margin: an owner-signature field, unset.** The margin is in pUSD per capture day over every baseline,
  pooled across bands, the same unit the rule decides in. It is not a per-band figure. Two ways to fill
  it:
  - **(A) Shadow-slot threshold.** Set the margin to the smallest daily net that would justify spending a
    shadow slot (operator time, capture, review) on the winner. The owner names that figure in pUSD per
    day, and the significance test then guards it.
  - **(B) Zero.** Set the margin to 0, and let Westfall–Young plus the 60-minute floor decide: any point
    that significantly beats every baseline with real quoting is a candidate.

  Either choice changes the decision rule digest above, which must then be recomputed before signing.
  (Review round 4 agreed with B, conditional on the null-row fix above; the economic bar then belongs to
  promotion, §10.)
- **Cost coverage: at most 2% of decisions without a markout over the panel, and at most 10% on any one
  capture day (PROPOSED; both in the rule digest).** A fill-cost decision whose tape context or table cell
  is missing falls back to the 0.0043 floor. That is a silent substitution, so `score` bounds it and the
  receipt reports the shares (`max_cost_unavailable_share` = 0.02 and
  `max_cost_unavailable_share_per_cluster` = 0.10).
  - The per-day bound exists because a pooled bound alone lets one day at 50% holes pass at about 1.8%
    overall.
  - The receipt lists each hole once per (capture day, condition_id) in `unavailable_by_day_and_band`,
    with its instants, the strategies affected, the decisions counted and the first and last instant, so
    each hole can be traced and the receipt does not grow with the strategy count. The shares and bounds
    still count every decision.
  - A kept band queried on a day whose tape has **no row at all** for it is not counted in the share. It
    is a coverage hole, and `score` refuses on it outright (an ID-case mismatch also shows up this way).
  - What the 2% tolerates is the residue: isolated missed capture minutes that leave the latest row more
    than 120 s old, and table cells the provider cannot price.
  - 2% is about 29 minutes of a 1,440-minute day. Above it, the floor would be pricing a material part
    of a point's fills.
  - 0 would refuse a whole panel over one missed capture minute. The owner may set it to 0 instead.
- **Toxicity keying (by design).** The build 2 table keys its hazard by the exposure minute's context and
  its markouts by the trailing context at the fill instant. That is safe here, because the frontier reads
  only `adverse_markout_upper`: the runner prices each fill at max(0.0043, that upper bound), and the
  envelope max(pooled, rows) is never below the pooled value. The hazard keying never enters this rule.

## 4b. Bands that closed before their capture day (scored mode)

A capture day's first hours (10-17T00:00–04:00Z is local 10-16 in the US zones) can hold a horizon −1
descriptor. For example, target 10-15 closes 10-16T04:00Z, inside the shadow embargo.

- In `score`, `cli.schedule` drops such a band, one whose descriptor close is at or before the start of its
  bundle's UTC day, **before** checking its close. It decides from the descriptor stream only, and lists the
  band in `embargoed_bands` with reason `closed_before_day`.
- A band that closed before the day began can earn nothing that day, so this loses nothing.
- Every other embargoed close still refuses the whole scored run. `score` drops nothing else.
- **A close inside the reserved window (09-30..10-15) is never dropped this way.** It always reaches the
  close check and refuses. The panel's first day, 10-17, cannot hold one, but the guard keeps the reserved
  contract absolute (tested).

## 5. Competitor-response model (fitted before this read; dates ≤ 2026-09-29)

The model is `maker_core.frontier.share_decay`. It is fitted on the RE-1 decision projection, with sessions
on 2026-09-23..25. A grid least-squares fit in share space gives a per-session k and τ for
x(a) = k(1 − e^(−a/τ)). x and k are extra competing Q per unit of our own Q (dimensionless). A session
whose τ lands on an edge of the τ grid is not identified: it is disclosed but excluded. The three bounds
are:

- `none`: x = 0;
- `central`: the median k and median τ over identified sessions (k = 5.01, τ = 5.0 min);
- `full`: the largest identified k (11.66, attempt 1), applied from a = 0. With no other competition it
  caps our share at 1/(1 + 11.66) ≈ 7.9%.

`full` is a bound reported beside the central fit, never used on its own to decide. The largest raw
observed ratio (59.6, attempt 5 after its quote drifted off mid) is kept in the fits as a diagnostic and is
not the bound.

Decay digest: `07a5507c72b052c90898b72751e786c6c2afcb7bbe187145f69c998f5adddaec`

The digest covers the fitted parameters and the SHA-256 of both RE-1 input files (`re1_sessions.json`
`192913fa…92499`, `re1_price_parity.json` `ef6a1017…462f2`), so a byte change in either input changes it
(build 4). The run result carries the digest, the code refuses a scored run whose model digest differs from the line
above, and **the model is not refitted on the panel**.

## 6. Power statement

Established findings §10r applies (master, 2026-10-14). The maker-P&L sign is **not decidable** on any
panel the governing preregistration allows: N_req = 706 event dates at delta = 1.0 pUSD per band-day,
branch UNDECIDABLE_AT_DELTA. Accordingly:

- the decision rule (§4a) is a pre-specified **selection** of a shadow-quoting candidate against the
  harness's own baselines, with family-wise control. It is not a net-P&L sign claim, an "edge" claim or a
  promotion claim;
- **as built, the test asks whether a point's modelled rewards exceed its modelled fill cost by more than
  the baselines'**. It does not test edge over the market;
- **serial dependence.** Capture days are not independent (§4a). The 2-day moving-block bootstrap is
  reported as a sensitivity and never decides;
- **power.** The panel is 2026-10-17..2026-11-13, about 28 capture days. At about 29 days the 120
  correlated points act like roughly 8–15 independent ones. The review (round 3) put the detectable
  difference at about 0.06–0.18 ¢ per quoted minute, so a margin of 0.02 ¢/min would never have bound.
  The margin is now an owner field in pUSD per capture day (§4a). Whatever value is signed, the rule is
  expected to be underpowered, and it then returns NO_GO;
- reward dominance (H1) is reported as a bounds statement beside it;
- the achieved spread across dates is reported.

## 7. Multiplicity

- All 120 points and 3 baselines are reported in full, in canonical grid order.
- No point is selected or reported as "best" without the full table beside it.
- Any later confirmatory read of a selected point needs a new preregistration and a fresh panel that this
  read has not touched. A selection made on this panel is a hypothesis, not a result.
- The only inferential statement is the decision rule's (§4a): Westfall–Young step-down max-T over the
  120 points, on the minimum over the three baselines, decides. Holm is disclosed as a sensitivity.

## 8. Panels and embargo (enforced in code)

`maker_core.frontier.embargo` refuses these dates; the runner, the decay fit and the RE-1 loader each call it:

- the reserved window 2026-09-30..2026-10-15, for every purpose;
- any fit date after 2026-09-29;
- any descriptive read dated 2026-09-30..2026-11-13 (the shadow embargo, which §10r left unchanged), and any
  scored read in that range before 2026-11-14T00:00Z.

The check covers the bundle day, the condition windows, every instant, trade times, market close and settle
times, and settlement facts.

- **The scored panel is 2026-10-17..2026-11-13** (`embargo.SCORED_PANEL`). It opens to a scored read only
  when the real UTC clock reaches 2026-11-14T00:00Z (`embargo.SCORED_OPENS_AT`). The reserved window
  never opens.
  - It starts on 10-17, not 10-16: a 10-16 bundle holds bands closing inside the reserved window, and
    `score` never drops bands, so such a band would refuse the whole scored run.
  - This was the master's decision in review round 3, and the review may revisit it.
- `python -m maker_core.frontier.cli score` checks, in order:
  - the clock;
  - that the toxicity table, its digest and the tape are all supplied;
  - that the margin is signed;
  - this document;
  - every bundle day lies inside the panel, before the bundle is opened. It then needs an intervals panel
  (`maker_core.replay.v2.panel.PANELS`) that declares the scored panel's windows. None exists today, so it
  refuses (`score_has_no_intervals_panel`) until a reviewed change adds one, before signing.
- Sources come only from `maker_core.replay.v2.intervals.sources` (v0.2 bundles plus the universe
  inventory), and the runner honours the declared windows.
- `calibrate` reads only the calibration days 2026-09-27..29. It drops any band whose close falls in a
  refused window, deciding from descriptor metadata alone, and refuses if a horizon loses every band.
- Its output is labelled **PIPELINE REHEARSAL**. It is not a power estimate, and **no number from it
  feeds the margin** (§4a), which the owner sets on the grounds given there.
- A market whose close falls inside a refused window is refused even if its capture day is allowed.
- Bundle hashes are recorded in the score receipt. The fill model binding, decay digest, decision rule
  digest and toxicity table digest are bound above.

## 9. Known simplifications

- Cash caps apply per band, with no cross-band capital.
- The baselines do not model RE-1's hold/requote observer.
- Coverage records are not used.
- The competitor-response model is fitted on 6 RE-1 sessions with enough samples, in one week.
- The runner keeps no state across capture days, so a capture-day cluster is exactly that day's run.
- The exit fee is a uniform upper bound (§4a), not a price-dependent fee, and it applies to `resting_sell`
  points only.

## 10. Shadow-to-live promotion bar (owner proposal) — DRAFT

**PROPOSAL for the owner. Not signed, and not part of the scored rule above.** No shadow-to-live promotion
preregistration exists yet: `docs/research/` has none, the live pilot runbook has none, and item 330 ties
G4 to the hurdle H. Review round 4 asked for the economic bar to be written down **now**, before any scored
result exists, so a winner cannot set its own bar.

**Proposed bar: a shadow profile is promotable only if its net is at least 1.00 pUSD per capture day.**
That net is measured on its own forward shadow days under the live envelope, which deploys at most
100 pUSD. Net means modelled reward minus fill cost minus the exit fee bound.

Derivation, from repository facts:

1. **The hurdle.** H = 1.00 net per day per 100 deployed (DECISION_LOG 2026-09-22). It also governs G1 and
   G4 (DECISION_LOG 2026-10-15), and G4 is item 330's go/no-go economic decision.
2. **The capital.** The live pilot envelope caps the isolated wallet at 100 pUSD and each order at 10 pUSD
   (`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`, an immutable envelope that may only be lowered).
   At that envelope, H is 1.00 pUSD per day.
3. **No scaling down (proposed).** A smaller deployment does not lower the bar. The cost of a shadow or
   live slot (operator attendance, capture, review) is per day, not per pUSD. The owner may choose to scale
   the bar with capital instead (0.01 × deployed).
4. **Units.** The frontier harness caps cash per band (100) but not across bands, so its scored
   per-capture-day net can assume more than 100 pUSD at work. The bar therefore applies to the **shadow
   profile's** net under the 100 pUSD envelope, never to the frontier's uncapped total.
5. **Cross-check against the measured costs, in the bar's own unit (pUSD per capture day).** The bar holds
   when

   bands per day × fill-pairs per band-day × cost per fill-pair + 1.00 ≤ reward per day.

   Assumptions (illustrative, for the owner to replace):
   - A fill-pair is one 20-share fill on each leg (40 shares). Since the first fill ends that band-day's
     quoting, this over-counts.
   - The cost per fill-pair is 40 shares × the settlement markout:
     - about 1.44 pUSD at −3.6 c per share, the worst of B2's counterfactual tape fits (fit 1 and fit 2, as
       relayed by master on 2026-10-17, short-horizon −0.5 to −3 c and settlement −1.3 to −3.6 c per share,
       underpowered; not yet recorded in an owning document);
     - about 0.17 pUSD at −0.43 c per share, the public maker markout to settlement (item 330).

   Worked through, with 5 bands a day and 0.2 fill-pairs per band-day (one fill-pair a day):
   - At −3.6 c the shadow profile needs at least 1 × 1.44 + 1.00 = 2.44 pUSD of reward per day.
   - At −0.43 c it needs 0.17 + 1.00 = 1.17.
   - Item 330 models 0.5–6 per band per day for contested next-day 20-share bands, so 5 bands would earn
     about 2.5–30 per day.
   - RE-1's one paid band-day earned +2.13 (k ≈ 1.05). That is below 2.44 for a single band, but within reach
     across several.
   - RE-1's realised −36.97 pUSD over five fills (exhaustion register §4) shows the fill rate, not the
     reward, decides the sign: at 1.44 per fill-pair, each extra fill-pair a day needs 1.44 more reward.
   - So the bar is demanding but reachable, and it is reachable only with a low fill rate per band-day.
5a. **Estimator: a one-sided 80% lower bound on mean net per forward day must be at least 1.00 pUSD.**
   The bound is LB = mean − 0.84 × SE, where SE is the larger of two estimates:
   - **Analytic:** the day-level sample SD (n − 1) / √n.
   - **2-day moving-block bootstrap:** `decision.mean_se_moving_block`, which reuses the decision rule's
     own `_block_resamples` unchanged.
     - Blocks are 2 consecutive observed forward days in date order (`sensitivity_block_length`), and they
       overlap: a start may be any day 0..n−2, drawn uniformly.
     - Blocks are concatenated and the last is cut so each resample has exactly n days. There is no
       circular wrap, so the first and last days sit in only one block start and are under-weighted.
     - 9,999 resamples (`replicates`), seeded `random.Random(20261114 + 1)` (`seed + 1`).
     - The SE is the sample SD (n − 1) of the 9,999 resampled means of daily net.
   - **Why a lower bound, not the point estimate.** At the point estimate, a profile whose true net is
     exactly 1.00 is promoted half the time, and promotion puts real capital at risk.
   - **Why 80%, not 95%.** The live wallet is capped at 100 pUSD, and kill rule K3 pauses quoting on excess
     fill losses. At 95% (1.645 × SE) the bar would demand 1.62–2.55 pUSD a day over 28 days, likely out of
     reach for any profile.
5b. **Minimum forward days: 28 capture days** (the scored panel's length), from a daily SD of 2–5 pUSD.
   That SD is an **ASSUMPTION** from review (Fable, round 5), not a measurement. It will be re-estimated
   from the shadow profile's own forward days, and the bound always uses that measured SE (5a), never this
   table.

   | Forward days n | √n | SE at SD 2 | SE at SD 5 | Mean needed at SD 2 | Mean needed at SD 5 |
   | --- | --- | --- | --- | --- | --- |
   | 14 | 3.74 | 0.53 | 1.34 | 1.45 | 2.12 |
   | 28 | 5.29 | 0.38 | 0.94 | 1.32 | 1.79 |
   | 42 | 6.48 | 0.31 | 0.77 | 1.26 | 1.65 |

   The mean needed is 1.00 + 0.84 × SE. At 14 days the SE at SD 5 (1.34) exceeds the bar itself, so the
   bound says little; 28 days is the first row where the SE is at most 1.0 across the assumed range.
   Fewer than 28 forward days is **inconclusive**, never a pass.
6. **What it is not.** It is a bar on the modelled net of a forward shadow, not a realised P&L claim.
   - Live use still needs the pilot's own gates.
   - Kill rule K3 (realised fill losses above twice the shadow prediction: pause) applies once quoting.
   - The live-fill calibration (LFC) sessions, starting with session 0 on 10-16, measure the real fill
     rate and fill cost. No LFC result is recorded in the repository yet. The owner should re-check this
     bar against session 0 to 1 before signing.

The scored rule's margin stays an owner field (§4a). Review round 4 favours option B (0) for selection,
with this bar governing promotion.

## 11. Signature

Signed: UNSIGNED
