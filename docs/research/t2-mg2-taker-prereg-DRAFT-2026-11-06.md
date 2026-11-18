# T2: paper taker on bound MG-2 vectors — draft preregistration

**DRAFT FOR MASTER / OWNER DECISIONS. NOT FROZEN. NOT READ AUTHORITY.**
This file proposes the complete T2 contract under the [edge trial charter](../operations/EDGE_TRIAL_CHARTER.md).
Read it to review or freeze T2; use [B's bound design](../operations/B_FORWARD_TEST_DESIGN.md) for B and
[the reservation](../operations/reserved-confirmation-window.md) for read permissions.
Unapproved proposals below are explicit freeze blockers, not delegated decisions.
No trial input, price, book, outcome, label, settlement or vector was opened for this task.

## 1. Authority, question and disclosures

- Basis: owner decisions 2026-11-05 ~21:50 (edge = accurately simulated fair-trial profit; early warning allowed)
  and ~22:03 (full plan approved), and the charter's minimums. The 2026-10-30 screen-only restriction on B's
  dates is superseded for qualifying frozen profit trials; B and MG-1 themselves stay bound.
- Question: does this one frozen MG-2 taker policy earn positive net paper P&L at the declared scale?
  Brier improvement, beating served, and surviving WS-3 cannot answer it. Prior is low: the development
  evidence did not establish model information beyond the market (findings digest; established findings §10ad).
- WS-3 is a separate, kill-only read on 09-30..10-14, outside the profit-trial Holm family. Its
  [signed prereg](ws3-early-warning-prereg-2026-11-06.md) has SHA-256
  `1f992edfc0c6ce9451bea27487d9fe0466ff661169045ff48d9358ab34a0a687`.
  Its [signature and amendments](ws3-early-warning-prereg-signature-2026-11-06.md) were read at
  `claude/ws-docs-head-c14-20261106`, commit `1a7edb0a5242be7f0643bf17f17642d76c70419f`, read-only.
  The signature's development projection is disclosed selection evidence, not T2 evidence.
- This draft was written after that development projection and before receiving any WS-3 trial result.
  Receipt of WS-3 may decide only whether T2 is killed, never its threshold, sizing, dates or scorer.
  An eventual freeze must disclose every signatory's previous reads and the WS-3 result/receipt or pending status.
- International Polymarket only; paper only; no exchange calls, orders, credentials, rewards or maker rebates.
  Settlement is the venue's actual winning market, never a WU/METAR reconstructed winning label.
  A PASS is simulation evidence at this policy and scale, not live permission or proof of scalable capacity.
- Source base for this draft: `origin/master` `22b3dd835e72f69d9e9fee5744a5c570c7f9a5eb`.
  The local main checkout's older documents were superseded by this explicitly fetched base; unrelated changes
  in that checkout were untouched. All writing is in `C:\wt\codex-t2` and the T011 task folder.

## 2. Strategy and exact reuse boundary

Reuse `src/weather/backtesting/t2_taker_rule.py` at
`edc11c56b2ace28ccaee5673c1f726732dea022d` on `claude/ws3-t2-taker-rule-20261106`, without editing its bytes:

| Pin | SHA-256 |
| --- | --- |
| Rule module | `aaf60a435f1551d1157ccb02790939bb0a0f5e9e6047a1544cd563791f82bdf6` |
| Schema family `src/weather/schema_families/t2_taker.py` | `886f5335582f72013af44cc35a808e009d8dd6f4163d6bcea7a349d93d21bd81` |
| Rule tests `tests/backtesting/test_t2_taker_rule.py` | `4c10a2737fbd887545bef94c9dade27eee750568b2cbd09df3dd48c67ee6e6dc` |

The additional T2 driver is **not implemented or pinned by this docs task**. Its allowed changes relative to
WS-3 are exactly: one MG-2 arm; B's date mask; measured primary latency plus the fixed sensitivity; global
capital validation; and a separate profit scorer/family receipt. Entry, fill, cost and cap functions are unchanged.
The pinned CLI requires two distinct arms and `evaluate` computes a paired difference: do not run that CLI with
an invented second arm or load served merely to satisfy it. The reviewed driver calls the pinned pure functions
for one MG-2 arm and uses its own pre-pinned single-look guard and profit scorer. These additions require review,
synthetic parity tests and SHA pins before freeze; their proposed names below are not existing commands.

- Decision instants: all captured T+0 snapshots, local hours 07 through 16 inclusive, on eligible dates and
  B's ten markets: atlanta, austin, chicago, dallas, houston, los-angeles, miami, nyc, san-francisco, seattle.
  Denver and Toronto are excluded. Use the module's market timezones, including DST; do not bucket by UTC day.
- Let `q` be the exported raw MG-2 band probability. No blend, calibration, refit, sharpening or renormalisation.
  BUY Yes if `q - a - 0.05*a*(1-a) - 0.01 >= 0.03`; BUY No if
  `(1-q) - a_No - 0.05*a_No*(1-a_No) - 0.01 >= 0.03`.
  The module's `1e-9` entry/cap tolerance remains exact.
- Within a snapshot, bands sort by cleaned band label. If both sides qualify, larger net edge wins; ties go
  to Yes. Snapshot ordering is `(captured_at_utc, event_slug)`. No discretionary ranking or random allocation.
- At most one successful entry per band; never both sides. At most three filled entries per market-day.
  A failed fill consumes no entry/capital cap and may be retried at the next snapshot.
  A filled entry is held through venue settlement, with no stop-loss, sale or mark-to-market substitution.

### Executable prices, displayed depth and capture gaps

The proposed unchanged rule is a **best-level-only depth walk**: buy at most the displayed size at the captured
CLOB best ask and stop there. It cannot buy ten shares using a display price or assume unlimited top-level size.
It does not sweep deeper levels. This is deliberate to preserve the signed rule; Q1 must settle whether the task's
"walking depth" requires a multi-level sweep instead. Such a sweep is a substantive new fill adapter, requiring
a separate explicit diff, review and pin before freeze; it cannot be silently called the same strategy.

- Use the captured `order_books_summary.csv(.gz)` token-side best ask, size, count, minimum size and book times.
  Never use Gamma `market_yes`, B's `p_market_yes`, midpoint, last trade or a derived display/VWAP execution price.
- Decision book at snapshot time `t`: latest usable row with `captured_at_utc + 15s <= t` and
  `captured_at_utc >= t-120s`. Both Yes and No tokens of every band need such a row for snapshot coverage.
- Primary latency `L = max(30, ceil(measured end-to-end p95 seconds))`, fixed before freeze from the Q2 receipt.
  It covers observation availability, decision and hypothetical order arrival, not just network round-trip.
  An unmeasured p95 is a freeze refusal, not permission to assume 30s.
- Fill book: earliest usable row in `[t+L, t+L+120s]`. Its ask `a'` must be no greater than the decision ask `a`.
  Select that row once; an empty/too-expensive/too-small row means no fill, not a search for a later better price.
  Positive ask count is required; shares = `min(10, ask_size_at_best)`. Reject below captured minimum order size,
  including a missing minimum. No invented depth, partial cap fill or hidden liquidity.
- Fee per share is **`0.05*p*(1-p)` at the executed ask `p=a'`**, plus 0.01 slippage per share.
  Since execution stops within the best level, depth-walk slippage is zero; the charged 1 cent is the charter's
  worse-of-one-cent-or-depth minimum. Do not shift `p` by the slippage before computing the fee.
- Reject non-finite/out-of-range prices, negative depth and inconsistent token mappings in driver preflight.
  The module skips a row with missing book time, a non-finite top-of-book field or
  `book_time_utc > captured_at_utc+15s`, and counts it. No extra stale-book cut is invented after reading.
- Missing decision row: no decision. Missing fill row: no fill. A zero-fill eligible cell contributes zero P&L.
  No interpolation, backfill or selecting books using a future realised winner.
- Each market-day needs at least 90% decision-row coverage over its 07-16 vector snapshots. The denominator
  is all those snapshots, regardless of signals or outcomes, and coverage uses all band tokens and both sides.
  Fix metadata/coverage masks before opening winner values or computing trades. Q4's all-ten rule applies below.
- Do not reuse one captured token-row's depth for multiple simulated orders: the driver must verify this
  invariant for the pinned engine; failure is INVALID, not a favourable capacity assumption.
- A NUL-line filter is allowed only under a separately pinned rule: drop iff a line contains byte 0x00,
  preserve kept bytes exactly, record dropped line numbers and source/used hashes. A dropped header or other
  parser refusal holds the read. Q8 must pin any filter and measurement of its coverage effects before freeze.
- Fixed latency sensitivity: rerun the frozen simulator within the same guarded look at `max(L,120s)`.
  It is descriptive only, never an alternative PASS arm, and does not release an additional look.

### Sizing, capital and net P&L (proposal requiring Q3 approval)

- Preserve principal caps: 25 pUSD per market-day and 100 pUSD per local target date, shared across markets,
  consumed in the module's decision order. Skip an entry that breaches either cap, never resize to fit.
  Caps consume on all simulated cells, including cells outside the final countable mask; do not reallocate
  unused caps after applying a countability mask.
- There are at most 300 filled shares per target date (10 markets x 3 entries x 10 shares).
  Fee is at most 0.0125 per share; fee plus slippage is at most 6.75 pUSD per date.
  Reserve 106.75 pUSD per eligible target date, including fees/slippage, with at most 25.675 per market-day.
- Proposed fixed paper bankroll: **4,803.75 pUSD = 45 x 106.75**, allocated to 45 segregated date budgets.
  No borrowing, leverage, reinvestment or recycling of payouts is needed. Unused date budgets remain cash.
  This is an explicit proposal, **not an assertion that the owner's real capital limit is this amount**.
  The $300 live-pilot cap is not approval for it. If the owner requires $100 total, this unchanged policy
  cannot claim a PASS under a larger simulated bankroll; a cost-inclusive chronological cash adapter must be
  specified and pinned before freeze instead. No such adapter is authorised or implemented here.
- All portfolio cash usage and simultaneous principal plus costs must fit the approved bankroll, even when
  settlements are delayed. Segregated budgets give this bound without assuming an unrecorded settlement time.
- Entry P&L = `shares * (venue_payout - a' - 0.05*a'*(1-a') - 0.01)`; payout is 0 or 1 for the purchased side.
  Rewards/rebates are zero. No financing income. Fixed operating-cost charge is proposed as zero; disclose this
  and report gross, fees, slippage and net separately. Any nonzero operating charge is set at Q3 before freeze.

## 3. Which vectors bind; freeze before reading

Only **`mg2_vectors_asof_capture.parquet`**, from the bound forward emitter, binds. `mg2_vectors.parquet`
(`last_in_hour`), recomputed vectors, current serving output and the WS-3 pre-D0 adapter are forbidden substitutes.
Use [MG-2 rule C4/C7/C9](mg2-composite-binding-2026-10-25/rule.md) and the
[input/export contract](mg2-composite-binding-2026-10-25/binding-plan.md) with B's subsequent clarifications.

The binding is `release-binding.json` SHA-256
`4e4dd97d0b2aa0eae920d6ee5406160ca8f0c16a001ba1615446702554a812fa`, rule SHA-256
`e761cc4eef097b80ae95fa03245871e8689a50125f4ad11ad00286218b17cdec`;
binding base `a8833a4658c914efc83a42edb2079becfcd3c7fd`, with identical bound files at its documented docs child.
The full release manifest, not a prose subset, controls all code/state hashes (L6 part `07a67425…`,
L6 own-state `800072c7…`, P3d_N state `c6cc39f7…`). B's own scorer pins are not T2's scorer pins.

1. Receive only B's allowlisted daily input bundles verified by its existing D+1 deadline; preserve receipt
   status, export cut, code/state/parser provenance and coverage/PIT/reproduction checks. No WS-3 late-bundle waiver.
2. **At vector export time**, record a create-only receipt binding source bundle/receipt hashes, emitter commit
   and module hashes, release-binding hash, layout/nowcast hashes, row keys, emission time and exact parquet SHA-256.
   Require equality with `mg2_emit_audit.json`'s `asof_capture.vectors_sha256`. A raw-input export hash alone
   does not bind later probability vectors. Future exports accrue to the same frozen manifest scheme.
3. Existing exports need their original pre-read provenance; a later rehash cannot prove they existed earlier.
   Before B or any claimant reads the dates, seal the selected vectors and their receipts. Use the same vector
   bytes B uses. If only inputs exist, master must arrange outcome-blind emission/sealing before those looks;
   this task does not emit them. Never recompute after observing B's result, even at apparently identical code.
4. The CSV adapter is a lossless row-key projection of those vectors into the pinned kernel's schema:
   `arm,event_slug,target_date,captured_at_utc,local_hour,range_label,q`. Pin its name mapping, float round-trip,
   duplicate checks and hash lineage. No probability change or late-data join is allowed.
5. **Before any trial value is read by this trial**, master signs the final prereg hash and freeze timestamp,
   records it in the decision log/charter, and pins every input-builder/adapter, driver, price filter, simulator,
   schema dependency, capital validator, inference scorer and family aggregator by commit and full SHA-256.
   Freeze environment/dependency versions, command arguments, synthetic rehearsal outputs and test hashes too.
   Unknown pins are a stop. This draft is not a filled freeze manifest.
6. Maintain an append-only export manifest and a single fixed look guard keyed to the final prereg hash,
   independent of output folder. Copying to a new folder never resets it. Read no trial value in a rehearsal.
   Validate all paths, hashes, schemas, date masks, claimant receipts and dependencies before the marker.
   Once the authorised read starts, exceptions produce an INVALID receipt and spend the look; no new strategy,
   repaired rerun, mask or resampling choice is selected from observed P&L.

## 4. Dates, countability and look order

Adopt B's **outcome-blind** rule, including [Clarification 5](mg1-countability-2026-11-03/b1-clarification-5-mg1-countability-and-b-dates-2026-11-03.md),
[Clarification 8](b1-clarification-8-countability-look-safety-2026-11-05.md) and
[coverage/drop-list Clarification 4](b-coverage-2026-11-02/b1-clarification-4-coverage-counts-2026-11-02.md).
Where the latter still carries a draft/acceptance placeholder, obtain master's accepted receipt, not an inferred ruling.

- D0 = 2026-10-29. Start with **the first 45 B-countable local target dates in chronological order**, no skipping.
  Every one must be input-countable. Every one of its ten market-days must have countable material coverage,
  a closed event with exactly one winner (presence only), and a venue-rule label key in the look-morning frozen
  manifest. WU reconciliation is recorded as a count, never an eligibility condition.
- 2026-12-12 is the 45th date only if none is missed. A missed date moves the 45th later. Follow the resulting
  bound MG-2 vectors, including C5's pre-existing post-12-16 MG-1 fallback; do not truncate to improve results.
  A delay into the >=12-17 row-28b claim needs a master scope/order ruling before any read, not a date substitution.
- Apply B's fixed capture-time price-coverage drop list to those 45. Its dates below 90% coverage are dropped
  without replacement. This uses counts only; B's capture-time prices are never T2 execution prices.
- Proposed T2 fidelity rule (Q4): a remaining date enters the primary only if **all ten** market-days pass the
  fixed 90% CLOB decision-coverage rule, vector integrity and uniquely mappable venue-market identity checks.
  Validate the complete possible-outcome ladder/token mapping before opening any winner identity, including
  zero-probability bands. No replacement of lost dates and no threshold chosen after inspecting P&L. Ambiguous
  structural labels detected in that blind pass exclude the date and are logged. A missing or unmatched realised
  payout discovered after the mask is sealed makes the trial INVALID; never drop that date based on which band
  won, invent a zero payout, or fall back to a weather label. Log every excluded date/cell/reason.
  Compute and seal masks from metadata before using winner identities; a structural failure discovered later
  is reported, never used for an outcome-selected recut. The module's looser any-market-day countability is
  not silently substituted for this T2 date rule.
- Zero-fill cells stay in the eligible denominator. Keep all engine trades and cap use, including non-countable
  cells, in a separate disclosed table. No wins/losses, realised temperatures, WU agreement, B verdict or
  model-vs-market performance chooses a date. A poor B/MG-1 result does not cancel a registered T2 final p-value.
- Claimants: MG-1 (NBM-family overlap), MG-2 gate/B, plus any overlapping earlier-frozen scope established by
  master before freeze (including L6_G, F8-MH and row-28b where relevant). PT-1 is NOT RUNNABLE and claims no date;
  WS-3's dates are disjoint. Master must close the scope list under Q5 rather than assume all other arms disjoint.
- Proposed single look: **2026-12-15 at 10:00 America/Toronto**, on the workstation, only after the actual
  MG-1 look receipt (or the Clarification-8 abandonment receipt accepted by B), recorded MG-1 window closure,
  MG-2/B look receipts and release record, and every required earlier overlapping claimant receipt exist.
  B's revised order is after Stage A and the 45th date's ledger row, expected 12-14 or later, not a guaranteed 12-13.
- If any prerequisite is absent, take no look. The deterministic fallback is 10:00 local on the first later
  calendar day after all prerequisites exist, with a hard last look **2026-12-28 at 10:00 local**. If not ready
  then, close UNTESTABLE without opening T2 values. Do not shorten B or MG-1 to meet T2's timetable.
  Family aggregation at 12-28 follows that final receipt. Master must resolve actual shared-date dependencies
  before freeze; this rule grants no T2-first exception.

## 5. Primary estimand, scale, inference and multiplicity (proposed)

The unit is a countable **market-day**, in pUSD. Let `Y[d,m]` be its sum of net entry P&L (zero for no fills).
`M` is the equal-weight mean across the fixed ten markets and eligible dates. All markets/snapshots/positions
for a local target date stay together under resampling; snapshots, fills and bands are never independent clusters.

Proposed minimum scale, approved before freeze under Q6: **at least 30 dates, 300 market-days, 100 filled entries,
1,000 filled shares, and 1,000 pUSD aggregate principal deployed**, under the unchanged 10-share/25/100 caps.
All five floors apply to the primary eligible cells. Additionally `M >= 0.10 pUSD per market-day` (1 pUSD per
ten-market date) is the economic point-estimate minimum. Do not raise stakes after seeing profits to meet scale.
These are proposals, not numbers derived from T2 or claims of adequate power.

Use a new, pinned profit scorer; the WS-3 module's lower/upper percentiles at alpha 0.025 do **not** implement this:

1. Set `R=100000`, seed `20261106`, NumPy `default_rng` fresh for each method. For each draw compute the mean over
   all selected market-day cells, retaining all ten markets of each sampled date.
2. Method A: resample `n` dates with replacement. Method B: non-circular moving blocks of length 3 over sorted
   eligible dates, `ceil(n/3)` uniformly selected starts in `0..n-3`, concatenate and truncate to `n` dates.
   As in the signed WS-3 convention, adjacent means consecutive **countable** dates, even across calendar gaps;
   report the gaps. Block length, seed, draw count and linear quantile interpolation never change after freeze.
3. For each method form centred replicates `Z*=M*-M`. Basic one-sided 95% lower bound:
   `L95 = M - quantile_0.95(Z*)`. Robust primary lower bound is the **smaller** of A and B bounds.
   Raw one-sided p-value per method is `(1 + count(Z* >= M))/(R+1)` for the null mean <= 0;
   T2's p-value is the **larger** of the two. For any family threshold `a`, also report
   `L(a)=min_methods[M-quantile_(1-a)(Z*)]`. This is a finite-bootstrap approximation, not an exact small-sample test.
4. Freeze the family procedure now: every registered profit trial T1, T2, T3, T4 and each T4+ candidate gets
   one final p-value. At 2026-12-28 sort all `m` p-values ascending (trial ID breaks ties). Reject sequentially
   only while `p_(i) <= 0.05/(m-i+1)`, stopping at the first failure. Report adjusted p-values
   `min(1,max_(j<=i)[(m-j+1)*p_(j)])`. No independence assumption between shared dates is needed for Holm;
   each component trial still needs a valid p-value including any within-trial sequential-look correction.
5. Reserve **0.0125 one-sided** as T2's proposed local alpha ceiling (four initial trial slots). Added trials
   may tighten the effective Holm threshold but never relax this ceiling after T2 reads. An absent/unopened
   slot, registered kill, INVALID or UNTESTABLE trial occupies its family slot with `p=1`; do not reduce the
   family after seeing results. WS-3 and the B/MG-1 diagnostics are outside this profit family.
   Master must ratify a common family ledger and any T1 sequential p-value construction under Q7.
6. **PASS** requires all integrity/read-order/capital gates, every scale floor, `M >= 0.10`, robust `L95 > 0`,
   `p_T2 <= 0.0125`, Holm rejection, and `L(a_T2)>0` at the smaller of 0.0125 and its Holm step threshold.
   Before 12-28 any local positive result is **PROVISIONAL, FAMILY PENDING**, not final edge.
   Neither a second latency arm nor per-market/hour/threshold cuts can rescue it.

### Power gate and futility

Positive control before freeze: the pinned module and T2 driver must agree on a synthetic 10-share Yes fill
at 0.40: fee 0.012/share, slippage 0.01/share, net +5.78 pUSD on payout 1 and -4.22 on payout 0.
Synthetic cases must cover No complements, depth/minimum-size and cap skips, simultaneous sides/ties,
latency windows, missing books/winners, date-mask failures, global capital, no double spending of captured
depth, preflight/consumed-marker failures, block resampling and known Holm examples. Reproduce the pinned
module's golden synthetic output exactly where reused. T2 has a cash-zero comparator, with the raw bound
model's floor/fallback and no calibration; it does not compare against an artificially inferior forecast arm.

No power run is authorised here. Before freeze, project this exact P&L contrast/population/sizing on development
dates <=09-29 using the approved simulator; name the receipt hash, measured date-cluster SD, autocorrelation,
block-3 variance ratio, resulting MDE80 and power at the proposed +0.10 pUSD/market-day economic minimum.
Use variance units for kappa and SE units for r; apply the full countability rule, not covered counts alone.
Meet method rule 6's power >=0.5 before launch, or close UNTESTABLE-by-design without reading trial values.
If a normal approximation is reported, disclose its assumptions and use the conservative family threshold;
simulation must reproduce the actual statistic. The WS-3 projection of a negative 5-cent/share kill effect is
not this positive-profit power calculation. Report realised/projected SD and population at the final look.

**No interim T2 looks or sample-size re-estimation.** WS-3 is the sole external early kill:
MG-2 KILL means T2 is not frozen; NOT_KILLED, UNTESTABLE or UNTESTABLE-by-design permits proceeding through the
remaining freeze gates, with no evidence of edge. Served's result triggers nothing. At the one final T2 look,
also report the pinned engine's kill statistic: the larger date-cluster/block-3 upper percentile bound at
alpha 0.025, 2,000 draws, seed 20260921. If it is below zero, KILL; it never creates a PASS.
Otherwise failure of PASS means NO EDGE DEMONSTRATED, or UNTESTABLE if floors/power fail, or INVALID for
integrity/read breaches. Registered kills remain in the family as p=1. No re-cut or rerun.

Method §5 rule 7 / the forward checklist prescribes interim futility looks for new tests. This single-look
proposal follows the charter/task instead; **master must rule on that explicit conflict (Q9) before freeze**.
Do not conduct those interim reads on B's dates by default.

## 6. Frozen receipt and reporting requirements

The create-only final package must contain the prereg/signature/export/code/environment manifests; exact command
and guard; claimant receipts; B's 45-date set and drop list; all fidelity masks/reasons fixed without outcomes;
all trades and per-market-day/per-date P&L (including no fills); cash/principal/fees/slippage; unfilled signals
and cap/price/minimum-size/gap skips; missing/unusable/collision/NUL counters; sample sizes and all minimum-scale
checks; both inference distributions/bounds/p-values and seed; latency receipt and sensitivity; power receipt and
realised/projected ratios; raw local verdict and final Holm ledger/receipt. Record actual times, source/used
hashes and any failed attempts. Distinguish loss, low power, missing capture and invalid simulation.

Disclose existing retrospective unread dates vs genuinely forward accrual, policy selection on dev/WS-3,
training coverage fallbacks and counts, settlement delays, approximate snapshot fills and no guaranteed
continuous book availability, depth truncation, allocated rather than recycled capital, operating-cost convention,
date dependence/gaps, all shared tests and their ordering, any amendments, and every excluded date/cell.
Per-hour/market/direction and 120s sensitivity are descriptive only. No favourable subset earns a claim.
Keep the run, logs and failures. Every kill goes to EXHAUSTION_REGISTER §6 and the never-cleaned archive by
copy, with script/input/output hashes and index; master owns STATE_OF_PLAY and DECISION_LOG updates.
Do not write those files in this task. No computed results or pretend pins are supplied by this draft.

## 7. Open choices — all must close before freeze

| ID | Decision owner | Concrete decision / evidence required |
| --- | --- | --- |
| Q1 | Master; owner if changing policy | Accept the unchanged best-level-only depth walk, or require a separately specified multi-level fill adapter; reconcile any change with the signed WS-3 same-module promise. |
| Q2 | Master | Supply the measured end-to-end latency source, measurement method/window, full receipt SHA and numeric p95; ratify `L=max(30,ceil(p95))` and the descriptive `max(L,120)` sensitivity. No trial prices/outcomes in calibration. |
| Q3 | Owner, via explicit recorded decision | Approve real per-market/total capital limits for the 4,803.75 pUSD segregated paper-bankroll proposal and zero fixed operating cost, or commission and pin a chronological cost-inclusive cash adapter at the actual smaller limit. |
| Q4 | Master | Ratify all-ten T2 fidelity-date mask/no replacement, accepted B Clarification-4 provenance and identity/collision failure handling; measure integrity-cap base counts outcome-blind before approving them (method rule 17). |
| Q5 | Master | Close the claimant scope/order list; confirm 12-15 10:00 with deterministic later fallback/deadline, valid MG-1 abandonment handling, and any >=12-17 row-28b overlap. Reconcile the reservation's narrow MG-2/B text with the later owner charter before freeze. |
| Q6 | Master / owner for economic minimum | Ratify 30 dates/300 cells/100 fills/1,000 shares/1,000 principal and +0.10 pUSD/cell minimum; obtain the positive-profit power receipt. Failed power cannot be waived silently or replaced with WS-3 kill power. |
| Q7 | Master | Ratify the proposed centred-bootstrap scorer, robust bound, 0.0125 local ceiling and common Holm registry including T4+ and T1 sequential correction; assign final family aggregator and 12-28 receipt. |
| Q8 | Master / implementation owner | Review, implement and pin the single-arm driver, CSV projection, optional NUL filter, export sealing, capital/depth validation, inference scorer, fixed guard and all dependencies/tests; obtain exact vector export provenance. No data read by this docs task. |
| Q9 | Master | Rule explicitly on single look versus method/checklist interim futility requirements; approve the exact outcome taxonomy and final kill statistic. Preserve B/MG-1 gates and no-read order. |
| Q10 | Master | Attach WS-3's signed MG-2 result/receipt when available; KILL cancels freeze. Obtain signatory prior-read disclosures and a final signature/hash before any T2 input value is read. |

## 8. Conflicts and handback boundary

There is no authorised conflict resolution by this draft. B's 45-date rule/drop list and MG-1's receipt/closure
remain controlling. Nominal 10-29..12-12 / ~12-15 dates cannot override delayed countability or the look chain.
The reserved status remains RESERVED for the MG-1 NBM family, with a separate post-09-29 embargo; the later
11-05 owner charter permits qualifying profit trials but does not itself complete T2's freeze or claimant checks.
The 10-30 released window cannot PASS and is disjoint from T2. PT-1 is not revived by borrowing its policy.

The outstanding implementation conflicts are precise: the pinned engine is top-level-only, two-arm and kill-only,
with per-date principal caps rather than a global cash ledger, and its native countability permits partial dates.
This draft states the required driver differences and proposes a capital bound instead of claiming those features
already exist. The method's interim-look requirement also needs the stated master ruling.
Only this dated draft is added; no B/MG-1 rule, reserved window, production state or other agent branch is changed.
