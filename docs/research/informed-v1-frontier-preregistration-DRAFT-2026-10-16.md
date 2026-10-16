# informed-v1 candidate frontier — preregistration DRAFT, 2026-10-16

**Status: UNSIGNED DRAFT.** This document grants no authority: no live, shadow or scoring authority, and no
panel read. A scored read is impossible in code until three things happen: the owner signs this document; a
reviewed change pins its SHA-256 in `maker_core.frontier.prereg.SIGNED_PREREGISTRATION_SHA256`; and the
grid hash below still equals `maker_core.frontier.grid.GRID_HASH`. The design note is under item 330 (build
3). **Read when:** reviewing, amending or signing the informed-v1 frontier read.

## 1. Question and hypotheses

The question is which quoting rules on the informed-v1 grid earn the most liquidity reward per band-day,
net of the modelled adverse cost and of other makers' response to our quote, compared with not quoting,
the RE-1 blind quote and informed-v0.

- **H1 (reward).** For each grid point, the reward under the `central` competitor-response bound is
  reported with the `none` and `full` bounds around it. A point "earns more reward than a baseline" only
  if its `full`-bound reward exceeds that baseline's `none`-bound reward. This is the dominance rule: it
  holds under every response assumption.
- **H2 (net, bounds only).** Reward minus the modelled adverse cost (filled shares × the markout from the
  fill-cost provider, never below 0.0043) is reported per point under all three bounds. Realised
  settlement and resting-sell P&L are reported beside it. **No sign claim is made for net P&L** (§6).
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
- **Fills.** Fills come from the injected fill model. Until build 1 lands, the stand-in is the frozen v2
  price-path predicate, reported under both `strictly_through` and `at_price`. After build 1 lands, the
  primary fill model is fill v3 (queue-aware), with both v2 bounds kept as brackets.
- **Adverse cost.** The adverse cost per filled share is max(0.0043, the provider's markout upper bound).
  A provider veto (`BURST`, `SWEEP`) suppresses the quote. Until build 2 lands the provider is constant.
- **Inventory P&L.**
  - Held shares settle on the captured settlement fact.
  - A resting-sell fill is booked as the locked pair value, 1 − entry − complement price.
  - Shares with no settlement in the bundle are counted, not valued.

## 5. Competitor-response model (fitted before this read; dates ≤ 2026-09-29)

The model is `maker_core.frontier.share_decay`. It is fitted on the RE-1 decision projection, with sessions
on 2026-09-23..25. A grid least-squares fit in share space gives a per-session k and τ for
x(a) = k(1 − e^(−a/τ)). The three bounds are:

- `none`: x = 0;
- `central`: the median k and median τ;
- `full`: the largest reaction observed in any session, applied from a = 0.

The fitted values and their digest are recorded in the item-330 build-3 note. The run result carries the
digest, and **the model is not refitted on the panel**.

## 6. Power statement

Established findings §10r applies (master, 2026-10-14). The maker-P&L sign is **not decidable** on any
panel the governing preregistration allows: N_req = 706 event dates at delta = 1.0 pUSD per band-day,
branch UNDECIDABLE_AT_DELTA. This read is therefore **descriptive and bounds-only**:

- no net-P&L sign, no "edge" and no promotion claim may be drawn from it;
- reward dominance (H1) is the only comparative statement, and it is a statement about bounds, not a
  significance test;
- the achieved spread across dates is reported.

## 7. Multiplicity

- All 120 points and 3 baselines are reported in full, in canonical grid order.
- No point is selected or reported as "best" without the full table beside it.
- Any later confirmatory read of a selected point needs a new preregistration and a fresh panel that this
  read has not touched. A selection made on this panel is a hypothesis, not a result.
- If a later amendment adds any interval statement, it uses a Holm adjustment over the 120 points × 3
  baselines family. No such statement is preregistered here.

## 8. Panels and embargo (enforced in code)

`maker_core.frontier.embargo` refuses these dates; the runner, the decay fit and the RE-1 loader each call it:

- the reserved window 2026-09-30..2026-10-15, for every purpose;
- any fit date after 2026-09-29;
- any descriptive or scored read dated 2026-09-30..2026-11-13 (the shadow embargo, which §10r left
  unchanged).

The check covers the bundle day, the condition windows, every instant, trade times, market close and settle
times, and settlement facts.

- A scored panel therefore starts no earlier than 2026-11-14.
- A market whose close falls inside a refused window is refused even if its capture day is allowed.
- Panel dates, bundle hashes and the bound fill model must be added in a signed amendment of this document
  before a scored read.

## 9. Known simplifications

- Cash caps apply per band, with no cross-band capital.
- The baselines do not model RE-1's hold/requote observer.
- Coverage records are not used.
- The competitor-response model is fitted on 6 RE-1 sessions with enough samples, in one week.

## 10. Signature

Signed: UNSIGNED
