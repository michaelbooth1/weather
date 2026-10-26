# PT-1: cool-season paper test, pre-registration (DRAFT)

> **Repository copy, filed 2026-10-26 in the docs head.** Copied unchanged from the coordinator's draft (raw
> sha256 `50ada8de71268c66aa0a4489385126b76a65e8bb49abbea74e7f58bcae487447`) except for this note. **DRAFT, not bound; its owner questions are OPEN.** `PT_D0` stays unset and no rule sha is pinned until master binds it.
> Answers go to the [decision log](DECISION_LOG.md) (owner) and today's state to the [state of play](STATE_OF_PLAY.md),
> not into this text. Items marked master are master's rulings, not the owner's.

- **Status:** DRAFT for master and the owner, written 2026-10-25 on the workstation. Not bound. `PT_D0: UNSET`.
  No rule sha is pinned yet. Nothing here has been run, fitted or scored.
- **Owner basis:** 2026-10-25, verbatim "Yes to all", approving among others item (2) "A paper test for the
  cool season" (relayed by master-agent). **No DECISION_LOG row exists for it yet** (DECISION_LOG on
  `origin/claude/docs-head-20261026` @ `50ea908ee` ends at 2026-10-24); §10 Q1 asks for one.
- **Paper only.** No order is placed, cancelled or signed. The evaluator has no order path (§8.4).
- **Written blind.** The author read no outcome, label, price, book, market, settlement, 88a or panel row
  dated after 2026-09-29, and no MG-1 forward output. Every number is quoted from a cited record and is
  selection evidence only.
- **Sources read:** AGENTS.md; STATE_OF_PLAY (`docs-head-20261026`, dated 2026-10-24);
  `reserved-confirmation-window.md` (same head); FINDINGS_DIGEST (same head); MODEL_IMPROVEMENT_METHOD
  (`origin/claude/docs-head-20261025` @ `6596e6f6e`); DECISION_LOG rows to 10-24; MG-2 `rule.md` and
  `binding-plan.md` (`origin/claude/mg2-c7-asof-gate-20261025` @ `525effe62`); the option B design
  `C:\t\bdesign\B_forward_test_design.md` and `C:\t\bdesign\retrain_overlap.md` (both 2026-10-25 20:03).
  `git grep -i "cool.season|paper test|paper-test"` over `origin/master` and the 60 most recent
  `origin/claude/*` heads found no earlier cool-season or paper-test draft (only an unrelated item-57 line).

## 1. The question (distinct from B and MG-2)

**Would a frozen, mechanical paper trading rule make money after fees and slippage at the prices actually
on offer at capture time, on fresh cool-season dates?**

Three forward tests now share the season. Each asks a different question:

| Test | Question | Primary |
| --- | --- | --- |
| MG-2 | Does the MG-2 composite beat MG-1? | Brier(MG-2) − Brier(MG-1), 00-16 and 13-16 |
| B | Does MG-2's capture-time band forecast beat the market's capture-time price? | Brier(MG-2) − Brier(market), 07-16 |
| **PT-1 (this file)** | Is the candidate's information **tradable**: net paper P&L of a frozen rule against captured executable prices | Net paper P&L per filled share, 07-12 |

PT-1's verdict never counts toward B's or MG-2's, and theirs never count toward PT-1's (§6.3).

## 2. The candidate (frozen, no new fit of the forecast)

**C-PT = the pre-13 half of the bound MG-2 composite**, at MG-2's binding hashes, read on the as-of-capture
path (MG-2 rule §8 C4/C7):
- MG-1 plus lane L6's own-observations stack; at 07-12, mu = v2_mean + a_h + b_h (N − v2_mean),
  sigma = max(v2_stddev, 1), MG-1's floor and band mapping; L6 part sha256
  `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9` (MG-2 rule §1);
- the same code commit and `release-binding.json` MG-2 binds. If MG-2's binding changes the L6 part before
  its D0, C-PT follows that binding; after PT-1's rule sha is pinned, nothing changes.

**Why only the pre-13 half, and only 07-12.**
- P3d_N, the post-13 half, is trained on Aug-Dec 2021-25 and covers target dates 08-01..12-16 only
  (B design §5, citing MG-2 C5). From 12-17 its slot silently becomes MG-1, and PT-1's dates start after
  12-11 (§4). On today's evidence MG-1 carries nothing beyond the floor at 13-16 (blend R 0.9858 against
  floor-only 0.9845; MODEL_IMPROVEMENT_METHOD §3, EF §10ad).
- 07-12 is where the loss sits (MODEL_IMPROVEMENT_METHOD §1), and the pre-13 half is identical on every
  PT-1 date.
- No refit is made for the cool season. That is the point of the test: does the frozen August-September
  information hold up, tradably, in December-February?

**Not candidates:** `last_in_hour` vectors (refused as input, method §3 rung 3); any retrain-family
candidate (§5.4); any candidate chosen after `PT_D0`.

**Trading probability q (frozen at binding).** The rule trades on a walk-forward log pool of the floored
market and C-PT, not on C-PT alone, because C-PT alone is worse than the market at 07-12 (L6 +0.0081
[+0.0062, +0.0101] Brier, B design §4, R-H atlas `ff7ee231…`):

```text
log q_b ∝ (1 − w_h) · log F_b + w_h · log p_b      (renormalised over bands the rule-4 floor allows)
F = capture-time market mid p_market_yes with the rule-4 floor mask, renormalised
```

- w_h for each local hour h in 07..12 is fitted once on development dates ≤ 2026-09-29 (walk-forward,
  then frozen on all dev dates), with a DEV_WINDOW_LEDGER row before the fit. Its table's sha256 is bound.
- **Feasibility gate (before PT_D0, development only).** If every w_h < 0.05, q is the floored market and
  PT-1 would only re-run L11's floor-only trade. PT-1 is then **NOT RUNNABLE** for this candidate and is
  reported to the owner instead of spending dates. The dev evidence that the blend weight of NBM-family
  arms is about 0 (EF §10ad; P3d_N at 13-16) makes this outcome plausible; nobody has measured w for L6
  at 07-12 against the market.

## 3. The paper decision rule (what a paper trade is)

All inputs are dated by **receipt**, never by observation (method §3, the L11 look-ahead lesson).

| Element | Rule |
| --- | --- |
| Markets | The 10 US markets of B and MG-2 (Denver excluded: KDEN from 10-23 is unsupported for model scoring, DECISION_LOG 10-23). |
| Event | The market-local T+0 event (the only one the candidate serves). |
| Decision instants | Every captured snapshot s whose local hour is 07..12 and that has a C-PT vector. |
| Price at decision | The latest captured order-book snapshot for the band's YES and NO tokens with receipt time ≤ `captured_at_utc(s)` and age ≤ 120 s; best ask a and displayed size at each ask level. No book within 120 s means no decision at s (counted, not a void). |
| Fee | Venue weather taker fee per share `0.05 × p × (1 − p)` at the fill price (EF §10o; makers pay 0, but every paper trade is a taker). |
| Slippage haircut | σ = 0.01 pUSD per filled share, charged on top of the walked fill price. |
| Entry test | BUY YES on band b if q_b − a_YES − fee(a_YES) − σ ≥ θ; BUY NO if (1 − q_b) − a_NO − fee(a_NO) − σ ≥ θ. θ = 0.03. A band never holds both sides. |
| Latency and fill | Immediate-or-cancel limit at the decision ask a. Filled against the **first** captured book with receipt time ≥ `captured_at_utc(s)` + 30 s and ≤ + 150 s, walking levels priced ≤ a. Fill price = size-weighted average of the levels taken. No such book, or no depth at ≤ a, means no fill (recorded). |
| Size | 10 shares per entry, or less if the walked depth at ≤ a is smaller. |
| Position limits | One entry per (date, market, band, side); at most 3 entries per (date, market); paper notional (shares × fill price) ≤ 25 pUSD per (date, market) and ≤ 100 pUSD per local target date fleet-wide, taken in snapshot-time order. These mirror the live envelope (event notional 25, wallet 100) so the paper result is not built on sizes we would never run. |
| Holding | Held to settlement. No exits, no re-entry, no netting. |
| Settlement | 1 pUSD per share if the band wins under the venue-rule label (highest routine METAR, SPECI excluded, tenths °C half-up to °F; DECISION_LOG 10-23); 0 otherwise. |
| Net P&L per entry | shares × (payout − fill price − fee(fill price) − σ). |

**Price-store branch, fixed before PT_D0 by an outcome-blind check.** The rule needs receipt-timestamped
T+0 asks with depth. If the capture holds them (master names the store; `order_books_long` is a likely
candidate; B's market arm uses only the snapshot's `p_market_yes`, which has no ask or depth), the table above applies. If it does
not, a declared fallback applies instead and is recorded in a dated Clarification before PT_D0: decision
and fill price = `p_market_yes` + 0.02 (a pessimistic half-spread), depth unlimited up to 10 shares, same
fee and σ. The fallback is weaker evidence and the results file says so. The branch is never chosen after
PT_D0.

## 4. Dates: fresh forward, disjoint from every other claim

### 4.1 The claims already on the calendar

| Claim | Dates | Held against | Source |
| --- | --- | --- | --- |
| MG-1 reservation | D0 2026-10-15 .. MG1_LAST 2026-11-28 (provisional, may only move later) | NBM-guidance-to-band candidates, which includes C-PT | `reserved-confirmation-window.md`; `weather.mg1_reserved_window` |
| MG-2, Branch 2 (option 2 exemption, owner 2026-10-25, MG-2 only) | first 45 countable dates from MG-2 D0 (accepted 2026-10-28; 45th 2026-12-11 if all count) | MG-2's own single look, after MG-1's | MG-2 rule §3, §4.3; B design §9 |
| B | exactly MG-2's 45 dates | B's single look, run with MG-2's gate | B design §3.2 |
| Retrain window | armed, not dated; earliest from 2026-11-18 if R0 freezes 11-17 | retrain-family candidates only | `reserved-confirmation-window.md` |
| Outcome embargo | every date after 2026-09-29 | all reads, until a dated owner line opens a named test | STATE_OF_PLAY; DECISION_LOG 10-23 |

### 4.2 PT-1's window

- **PT_D0 = the first local target date after the later of:** (a) `MG1_LAST` as recorded in
  `weather.mg1_reserved_window`; (b) MG-2's 45th countable date as fixed by MG-2's countability ledger,
  which is also B's last date. Provisionally **PT_D0 = 2026-12-12**.
- **N = 45 countable dates** from PT_D0, counted with no skipping. Provisionally the 45th is
  **2027-01-25** and the read is on or after 2027-01-27.
- **Countable** = the MG-2 definition applied to PT-1's 10 markets: the date's outcome-free input bundle is
  verified by its deadline and passes the outcome-blind checks (§7), and the date is promotion-countable.
  Additionally, a date needs ≥ 90% of its 07-12 snapshots to have a receipt-dated book within 120 s, by the
  counts-only field in §7. A non-countable date moves the 45th date one day later.
- **Moves only later.** If MG1_LAST or MG-2's 45th date moves past provisional PT_D0, every date up to the
  new bound is dropped from PT-1 and PT_D0 moves with it. PT-1 never claims a date first.
- **Hard end 2027-03-15.** If fewer than 45 dates are countable by then, the look runs once on the
  countable dates if there are at least 30; below 30 the look is VOID. This is fixed now and is not a
  result-driven stop.
- **Fresh only.** No date before PT_D0 is scored by PT-1, including unread captured dates.

### 4.3 How double use is prevented

1. **Dates.** PT-1's set is disjoint from MG-1's reserved dates, from MG-2's and B's 45 dates, and from any
   date another bound forward test claims first. PT-1 takes the later dates by rule (4.2), so the existing
   claims never move to make room for it.
2. **Questions.** PT-1 asks the economic question (§1). Its forecast measures (§5.2) carry no α and cannot
   be cited as a second chance for B's question: a PT-1 result never rescues, re-cuts or overturns a B or
   MG-2 result, and the reverse holds too.
3. **Read order.** MG-1's look, then the MG-2 gate with B in one run, then PT-1. PT-1's scorer refuses
   until it holds B's look receipt (or a recorded B VOID or abandonment) and every PT-1 date has settled.
4. **Live sessions.** If any live maker session rests an order on a PT-1 date, every band-day it touches is
   dropped from PT-1 before any outcome is read, by the LFC §4 exclusion pattern (same event, same local
   quote date). A dropped band-day does not count against the coverage threshold.

**Alternative the owner may choose instead (§10 Q3):** B's design §7 item 2 allows a paper test on B's own
dates, with B's exact MG-2 as-of vectors, read after B's look. That would give an earlier read (after
2026-12-12) at the cost of reading the same 45 dates twice for two questions. This draft does not take it,
because the brief requires no double use of dates.

## 5. Metrics

### 5.1 Primary (one α, one look)

**E = Σ net paper P&L / Σ filled shares** over all PT-1 entries on countable dates (pUSD per share).
- Interval: fixed-market, date-clustered percentile bootstrap, resampling dates with all their entries,
  2,000 draws, seed 20260921; the crossed date × market interval beside it, not deciding.
- One-sided α = 0.025 at each bound used. The owner allocates the α (CAMPAIGN_LEDGER row before PT_D0).

### 5.2 Secondary (no α, reported beside the verdict)

- Total and per-date net P&L, trades per date, fill rate, fees paid, capital-days at risk.
- **Floor-only control:** the same rule with q = F (w = 0). Reported as E_F and E − E_F (L11: the floor
  alone produced the earlier "gain").
- **Placebo:** C-PT vectors deranged across dates within market, same rule; E_placebo.
- Capture-time forecast measures on PT-1's rows: Brier(q) − Brier(F) and R = Brier(C-PT) / Brier(market)
  per hour 07-12. These describe the information behind the trades; they are not B's test.
- Per-market and per-hour signs; the mid move 30 minutes after each fill (diagnostic only).

### 5.3 Power, shown as arithmetic (planning only; the binding recomputes it)

Assumptions: per-share settlement P&L SD about 0.45, 10 shares per entry, T entries per date, date-level
clustering inflating the SD by 1.5. Then SE(E) ≈ 1.5 × 0.45 × 10 × √T / (10 × T × √N) =
0.675 / (√T × √N) pUSD per share, and MDE80 = 2.802 × SE.

| T entries/date | SE at N = 45 | MDE80 at N = 45 | MDE80 at N = 60 |
| ---: | ---: | ---: | ---: |
| 5 | 0.045 | 0.126 | 0.109 |
| 10 | 0.032 | 0.089 | 0.077 |
| 20 | 0.022 | 0.063 | 0.055 |
| 40 | 0.016 | 0.045 | 0.039 |

So PT-1 can only confirm a large net edge, roughly 5-13 cents per share. A taker with no information
loses about 2.25 cents per share at mid (fee 1.25 plus σ 1.0), so a confident FAIL is reachable only if
the rule trades often. This is stated as a limitation, not hidden.

**Binding sizing rule.** At binding, the lane replays the frozen rule on the development dates ≤ 09-29
(dev prices are allowed) and computes T and SE(E) with the same bootstrap. If the projected MDE80 at
N = 45 is above 0.10 pUSD per share, N is 60 (fixed then, never later). If it is still above 0.10 at
N = 60, or projected T < 3, PT-1 is **NOT RUNNABLE** and goes back to the owner before PT_D0.

### 5.4 Retrain-window interaction

C-PT is not a refit of the served feature models. Under the ruling recommended in
`C:\t\bdesign\retrain_overlap.md` (the family is R0 and its successors), it is outside the retrain window
and PT-1's dates are exempt from it. If the owner rules otherwise, PT-1 drops any date the declared retrain
window holds, by the same moves-only-later mechanics.

## 6. Verdicts (fixed sample, one look)

Let [L, U] be the one-sided 97.5% bounds of E. H_PT is the minimum practically useful net edge, default
**+0.01 pUSD per share**; the owner may change it only before PT_D0 (§10 Q4).

| Verdict | Condition |
| --- | --- |
| **VOID** | Any §7 void condition, or fewer than 30 countable dates by 2027-03-15. No verdict; dates spent. |
| **NOT INTERPRETABLE** | A sanity control fails (§7.2). Dates spent; no pass or fail. |
| **PASS (paper-tradable)** | L > 0, E ≥ H_PT, at least 300 filled shares, and E − E_F > 0 (the gain is not the floor alone). |
| **FAIL** | U < H_PT: the rule's net edge is shown to be below the useful minimum. |
| **INCONCLUSIVE** | Anything else, including fewer than 300 filled shares. |

### 6.1 What a verdict triggers

- PASS: a report to the owner. It earns, at most, a separate pre-registration of a bounded live test under
  the pilot runbook. It is never a promotion, a live order, or a gate bypass.
- FAIL: recorded in EF/RF and the digest as "C-PT is not tradable as a taker in the cool season under this
  rule". Whether it feeds the 10-23 kill decision is the owner's call (§10 Q2); no agent stops the project.
- INCONCLUSIVE: dates are spent and not re-run. A next candidate gets a new pre-registration on later dates.

### 6.2 No peeking

- No interim look, no sample-size re-estimation, no change to θ, σ, size, limits, N, markets, hours or
  window after PT_D0.
- No PT-1 value that touches a price, a fill or an outcome is computed before the look. The evaluator
  runs exactly once, at the look, on the frozen code.
- The only post-PT_D0 edit allowed is a dated Clarification that grants permission to read (§10 Q1). It
  changes no design element.

### 6.3 No double use

PT-1 is never pooled with B, MG-2, MG-1, EDGE-1, LFC or any later look. A PT-1 result cannot be re-cut by
window, market, hour or threshold after the look.

## 7. Outcome-blind accrual, controls and void conditions

### 7.1 Daily, outcome-blind (permitted before the look)

- MG-2's daily input bundle and its receiver checks (MG-2 binding plan §9.3), extended to PT-1 dates: the
  exporter keeps running after B's last date.
- One row per PT-1 date in a create-only receipt ledger: the sha256 manifest of the snapshot, band and
  book files for that date.
- `check` on C-PT: coverage ≥ 90% of 07-12 snapshots, PIT, replay reproduction to 1e-12, parser version 2.
- **Counts-only book coverage field** (an addition the exporter needs, like B's market-coverage field):
  per market and hour, the number of snapshots with a receipt-dated book within 120 s. It carries no price,
  size or side.
- No label, settlement, price, size or market column travels in the daily channel.

### 7.2 Sanity controls (NOT INTERPRETABLE if any fails)

- **S1 identity:** with w = 0, the engine's q equals F to 1e-12 on every row, and its trades equal a
  separately computed floor-only run.
- **S2 placebo:** the placebo's lower bound L_placebo must be ≤ 0. A placebo that "makes money" means
  look-ahead or label leakage.
- **S3 positive control:** on the development dates, the frozen engine reproduces the binding-time dev
  replay output (its sha256 is pinned at binding) byte for byte.

### 7.3 Void conditions

- Any MG-2 void condition that touches the pre-13 half (MG-2 rule §7: PIT, replay, nowcast replay,
  parser, hashes).
- Any input, book or METAR row with a receipt time after the row's own decision time (fills use the
  post-decision book by design, §3; decisions never do).
- A missing or altered input-transfer receipt for a counted date.
- Any PT-1 date's outcome, label, price or book value read before the look.
- The look ran before B's look receipt (or recorded B VOID or abandonment) existed.
- Any hash differs from the binding.

## 8. Required artifacts and receipts

### 8.1 Before PT_D0

1. This rule, finalised, with its raw sha256 pinned in a pushed commit and in DECISION_LOG.
2. `python -m weather.reporting.scorecards.prereg_check` passes on it.
3. DECISION_LOG row(s): the owner's paper-test approval with this file's sha; the embargo carve-out for
   PT-1's single price and label read (§10 Q1); the α allocation.
4. `reserved-confirmation-window.md`: a dated PT-1 row (owner's file), recording PT_D0, the 45th-date rule,
   the moves-only-later mechanics and the scope "PT-1 economic question only".
5. CAMPAIGN_LEDGER row for PT-1's one decision.
6. DEV_WINDOW_LEDGER row (`pending`) for the w fit, the feasibility gate and the dev replay; filled after.
7. Binding manifest: MG-2 binding commit and `release-binding.json` sha; L6 part sha; w table sha; PT-1
   engine code sha; price-store branch (§3); dev replay output sha (S3); N (45 or 60).

### 8.2 Daily

Receipt-ledger rows and `check` results (§7.1). Counts-only, no values.

### 8.3 At the look

- One transfer only, to a separate inbox with its own manifest sha: venue-rule winners,
  `promotion_countable`, and the T+0 book snapshots for PT-1's countable dates.
- A create-only look receipt: every input hash, every output hash, the verdict, and a single-look marker
  that makes a second run refuse.
- A results file beside this rule; EF, digest and the item's status updated in the same change.

### 8.4 No live order path

- The engine runs on the workstation on transferred captured files. It imports no exchange client, SDK,
  credential, wallet-reader or `maker_core.runtime` module, and makes no network call. A test pins this
  with an import and AST scan (the MG-2 pattern).
- No credential, wallet or `config/local/` file is read.
- Nothing is registered on the capture host for PT-1 beyond the counts-only exporter field.

## 9. Dependencies and timing

| Step | Owner | Needed by |
| --- | --- | --- |
| MG-2 bound (binding commit, D0 10-28) and its exporter running | master | before PT_D0 (PT-1 reuses both) |
| Venue-rule label path on master (open commitment in STATE_OF_PLAY) | workstation, master | before the look |
| Price store named, counts-only book field added to the exporter | master | before PT_D0 |
| w fit, feasibility gate, dev replay, sizing (§2, §5.3) | a model lane, after current model-improvement priorities | before PT_D0 (by 2026-12-05 for review) |
| Rule sha pinned, DL and reservation rows | master, owner | before 2026-12-12 |
| Look | lane | after the 45th PT-1 date settles and B's look receipt exists (provisionally 2027-01-27) |

The drafting needed no workstation compute. The binding-time steps need one modest dev replay; they can
wait behind model-improvement work until early December.

## 10. Open questions for the owner (and master)

1. **Embargo carve-out.** The 10-23 row reserves the post-09-29 embargo "for that test", and B is being
   proposed as that test. PT-1 needs its own dated line allowing one price-and-label read for its dates, at
   its look, after B's. Does the 10-25 "Yes to all" cover that, to be written as a DECISION_LOG row?
   Recommended: yes, recorded with this file's sha.
2. **What a FAIL triggers.** Does a PT-1 FAIL feed the 10-23 kill decision, or only end this candidate's
   paper track? Pre-declare it before PT_D0.
3. **Dates.** Disjoint dates after B (this draft; first read about 2027-01-27), or B's own 45 dates under
   B §7 item 2 (read after about 2026-12-12, same dates read for two questions)? Recommended: disjoint.
4. **H_PT** = +0.01 pUSD per share as the useful minimum, and **θ = 0.03, σ = 0.01, 30 s latency**: confirm
   or change before PT_D0.
5. **Retrain family.** Confirm the ruling in `retrain_overlap.md` (the family is R0 and its successors), so
   PT-1's dates are not held by a declared retrain window.
6. **Candidate.** Keep the pre-13 half of MG-2 (no refit), or ask a lane for a cool-season refit of P3d_N
   (training months Nov-Mar) for 13-16, which would need its own selection evidence and a dated
   Clarification before PT_D0? Recommended: no refit; 07-12 only.
