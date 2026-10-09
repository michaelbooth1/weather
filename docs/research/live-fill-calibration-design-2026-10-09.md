# Next live test — design (2026-10-09, design only, no live authority)

**Owner 2026-10-09 ~14:40: "yes approved"** to: the fill-rule calibration question at a 100 pUSD worst-case budget, 40 shares, 8 sessions; the faster route (start once code is ready, about 10-20, with a dated clarification signed before any panel read that excludes the band-days carrying our orders, instead of waiting for 11-16); relying on the RE-1 hard limits plus the worst-case ledger `L` instead of first wiring the #180 guard. Still to confirm from the owner: the wallet is fresh, dedicated and funded with exactly 100; the attendance model. The pre-registration and code are still owner-signed / owner-started gates; nothing here authorizes an order.

Owner direction 2026-10-09: "design the best next live test. $100 budget ... a very deliberate test." Owner makes stop/continue
calls personally; no kill rule. [M] = measured/documented fact with citation; [J] = judgement. Paths relative to the repo.

## 1. Primary question

**Chosen: calibrate the fill rule on our own resting quotes, and record own-fill markouts.** Every pre-registered proxy
(desk study, replay v2, shadow) simulates the *same* RE-1-faithful quote and credits a fill only under two bracketing rules,
"strictly through" (primary) or "at price" (sensitivity) [M: `docs/research/maker-pnl-adverse-selection-preregistration-2026-10-01.md`
on `codex/maker-pnl-adverse-selection-20261001` §Estimand; `maker-shadow-runner.md` §Nightly scoring]. Four of RE-1's five fills
were at price, one strictly through [M: EF §10m; v3.2 spec §8.1]. Where reality sits between the rules decides how all three
proxies are read, and only own-account fills can tell [M: EF §8c]. Observation unit = a public print at or through our resting
price while we rest (dozens per session), not a fill (a handful).

Ranked by information per dollar [J]:

| Rank | Question | Why |
| --- | --- | --- |
| 1 | P(fill \| at-price print), P(fill \| strictly-through print), queue-ahead at post; own-fill markouts 1/5/30 min/settlement | Many events per dollar; leverages three proxies; fills accrue as a by-product |
| 2 | `f` / adverse selection on own fills directly | The decisive unknown [M: EF §1b.3], but ~3-6 fills at $100: 23% power at 21 days for ≥10 strictly-through fills under mapping A [M: v3.2 spec §8.3-8.4]. Descriptive only; collected anyway |
| 3 | Reward capture vs competition; touch vs 1-tick-back | k ≈ 1.05 and 2-4 min halving already measured [M: EF §10m]; a distance arm changes the quote the proxies simulate and halves the calibration sample |

Rejected arms: touch vs 1-tick-back (breaks proxy fidelity); informed-v0 pull on/off (no weather plugin, no live runtime on
master [M: `maker-shadow-runner.md` §Fair value; `maker-trading-guard.md` §Not yet]). One treatment, replicated.

## 2. Design

**Markets/bands.** The 12 built-in markets, local T+1/T+2 bands. Selection = the frozen RE-1 rule plus the 09-24 amendment
(rewarded, min size ≤ ours, rate ≥ 40/day, two-sided, spread ≤ 6 c, mid in [0.20, 0.80], displayed depth ≥ max(75, size)
each side, predicted `share_many` 0.15-0.70, rank by predicted reward), run 30 min before start, no human pick, owner veto of
the whole session only [M: `docs/research/liquidity-reward-epoch-preregistration-2026-09-20.md` §Selection; DECISION_LOG
2026-09-24; `live-testing-plan-2026-09-25.md`]. Bands inside an embargoed panel are excluded (§4).

**Quote.** Two backed post-only BUYs: YES at `m − d`, NO at `(1 − m) − d`, `d` = 1.5 c snapped outward; requote only when a
leg leaves [1, 3] c, at most four requotes; first fill on a band cancels the sibling and the lot is held to settlement
(RE-1-faithful stratum, exactly the quote the proxies simulate) [M: RE-1 pre-registration §Treatment].

**Size.** 40 shares per leg [J]. Reasons: the T+1/T+2 reward minimum is 20 shares [M: EF §10a], two-sided at 40 is
eligible; fill probability per print is price-time priority, so size barely changes the calibration ratios, while 75-share
legs cost up to 59 pUSD at the mid edge and three total-loss fills exceed the budget. Deviation from the proxies' 75 is
declared in the pre-registration and reported. If the band's minimum rises above 40 mid-session the band stops (RE-1 rule).

**Sessions.** 8 sessions × 360 min, one band per session (two bands in different events only if the workstation extends the
account-wide foreign-order check [M: EF §10m session 9]). Start :59-:05 past the hour after the METAR cluster, 13:00-18:00 ET,
so the session ends inside the UTC reward day [M: live-testing plan; RE-1 pre-registration §Reward day]. Run on the
**workstation, owner-started** [M: `informed-maker-design-2026-09-25.md` Direction 7; DECISION_LOG 2026-09-27 "capture host
stays credential-free"]. The capture host runs nothing live, so its 12:00-18:00 graded window does **not** bind; only a
`capture_colocated_v1` session would be confined to [00:30, 09:00) [M: pilot runbook §Prerequisites 8]. Not proposed.

**Inventory and exposure caps.** Dedicated wallet funded exactly 100 pUSD [M: pilot runbook §Immutable envelope]. Per leg
cost ≤ 32 pUSD (40 × 0.80); per band at most one filled leg; resting reserve `size × (p_yes + p_no)` ≤ wallet − 20 [J, from
RE-1's reserve model, EF §10n]. Worst-case ledger `L` = Σ cost of filled legs (valued at zero) + Σ maximum cost of resting
legs; a new band starts only if `L` + its reserve ≤ 100; the test ends when no band fits or after 8 sessions. No cross-market
over-commitment (Q-13 stays unmeasured by design).

**Settlement exposure.** Hold to settlement, no taker exit (fee `0.05·p(1−p)` [M: EF §10o]); redeem after venue resolution;
settlement mark from `data/settlements/<market>/ledger.jsonl` (WRH caveat, EF §10c).

**$100 as worst-case loss.** Every filled leg is counted at zero recovery and rewards are not netted; by the `L` rule
cumulative filled cost never exceeds 100, so the worst case is the budget by construction. Realistic: 4-6 fills at ~20 pUSD
each put most of the budget at risk; RE-1's settled lots were +6.43 on three and −13.30 on one [M: EF §10m].

## 3. Measurements

**Metrics (pre-declared).** Per band-session: minute journal (book, reward record, `share_many/single`, our legs, queue-ahead
= displayed size at our level before each post/requote); `N_at`, `N_thr` = public prints at / strictly through our resting
price on our side; `c_at = Σ filled / Σ min(print, remaining)` over at-price prints, `c_thr` likewise; fills (count,
partial/full, time to first fill); markouts at 1/5/30 min against the 88a two-sided mid (120 s tolerance) and at settlement
against the ledger winner; share-weighted mean markout; **informed-fill estimate** `f̂` = fraction of fills with 30-min markout
≤ −2 c and settlement sign (descriptive); reward: venue accrual per condition per UTC day, modelled `P_many`, `k`, paid credit
at 00:00Z (19:00 ET after 11-01); rebates via `/rebates/current` (likely below the 1-dollar minimum [M: pilot runbook §Stage 3]);
cash before/after by the item 330 identity [M: item 330 §3].

**Sources.** Own fills: authenticated CLOB `/data/trades` via the read-only wallet reader (`trades`: order ids, `match_time`,
`maker_orders`) and the RE-1 journal's `terminal_trades` + user stream [M: `wallet-reader.md`; `src/weather/market/wallet_reader.py:358-367`];
the manual order journal every 5 min (`fill_time` is "no later than") [M: `src/weather/market/order_journal.py`]. Public prints
and books: 88a (books per minute, `last_trade_price` continuous) [M: `maker_evidence_capture.py` ~327; `maker_evidence_stream.py:97-106`]
plus the RE-1 minute journal. Cash/positions: wallet reader snapshots in `data/wallet_ledger/`.

**Power, honestly.** 8 sessions ≈ 48 band-hours; RE-1 produced 5 fills in 11 sessions, so expect ~3-6 fills, budget-capped at
~5. `N_at` is unmeasured and must be counted from the RE-1 journals (dates ≤ 09-29) before signing [J]. If `N_at` ≈ 20, the
90% interval on `c_at` is about ±0.18: enough to separate "at-price prints fill us" (≥ 0.7) from "the queue eats them"
(≤ 0.3). Markout on 5 fills has SE ≈ 2 c: separates −0.4 c from −5 c, nothing finer. `f̂` on 5 fills is an anecdote.
**Plan changes:** `c_at` ≥ 0.7 → read desk study, v2 and shadow on the at-price rule (resolves `_FILL_RULE_DEPENDENT`; v2 OD11
option 2 becomes primary); `c_at` ≤ 0.3 with `c_thr` ≈ 1 → strictly-through stays primary; share-weighted 30-min markout
≤ −3 c on ≥ 5 fills → K3, pause and re-derive [M: `forward-plan-2026-09-23.md` §Kill rules]; zero fills in 8 sessions → the
depth-rule bands do not fill at 40 shares and the 0.001/min shadow hazard is revisited.

## 4. Interaction with pre-registrations

- **Replay v2 panel** (88a UTC 09-30..10-14, settlement 10-15, unread): our legs would enter 88a books and absorb prints on
  the quoted bands; Austin 10-03 was excluded for a mere look [M: DECISION_LOG 2026-10-05]. **No session before UTC 10-16.**
- **Desk-study decision panel**: T+1/T+2 quote-minutes for event dates 10-17..10-30, extended to ≤ 28 dates (to 11-13) if
  `N_req` is 15-28 [M: desk-study pre-registration §Part 2; `maker_shadow_panel.EMBARGOED_UTC_DAYS`]. Same contamination (our
  size counts toward its depth rule and competes for its prints). **Avoid 10-15..11-13**, or sign before any panel read a dated
  clarification excluding band-days carrying our orders; avoidance is cleaner [J]. 89a panel B (same-day, 09-25..10-08) is
  closed by date.
- **MG-1**: reserved only against NBM forecast scoring; maker use is exempt [M: `reserved-confirmation-window.md`]. No conflict.
- **Shadow parity**: defined on identical tapes, unaffected; but our live legs appear in the shadow's public books, so shadow
  paper fills on bands we quote live are not independent: report those band-days separately [J].
- **Sequencing rulings**: SoP critical path 4 (live not before the v2 look and ≥ 7 days of parity); decision 2026-09-24 (maker
  migration before RE-2); 2026-09-25 (d) (pause + bleed limit in code before any RE-1 resumption). This is RE-1-faithful
  calibration, not RE-2, but the owner must say so.
- **Dates**: clean from UTC 11-14 (11-01 if #263 gives `N_req` ≤ 14). Avoid 11-01 itself (DST; payout time shifts).

## 5. Prerequisites

| Item | State | Who |
| --- | --- | --- |
| Dedicated wallet, funded 100 pUSD, no manual positions, fresh L2 credentials | unconfirmed; isolation needs a fresh wallet [M: EF §10i] | owner |
| #180 ledger OBSERVED: `config/local/portfolio_campaigns.json` (start = funding instant, contributions 100, rules by the 12 event-slug prefixes), snapshots in `data/wallet_ledger/`, `maker_core.portfolio report` exit 0; watch `fee_unknown`/`history_complete` [M: `src/maker_core/portfolio/ledger.py`] | not built for a live wallet | production; owner (values) |
| Guard: `OrderGate.authorize` before each post + `CancelAllPort` → RE-1 cancel-all, or an owner decision that the RE-1 hard limits suffice | guard has no live consumer [M: `maker-trading-guard.md` §Not yet] | workstation / owner |
| #229 reseal, C3 rehearsal, econ-snapshot gate | sealed Stage 0/1 lane only (`src/weather/**` hash glob) [M: `international_live_wrapper_sealer.py:118-170`]; that lane cannot rest a quote, so not on this path. Whether the RE-1 preflight reads the econ gate is unverified; the matcher PR lands N5 anyway | workstation checks |
| Code: `codex/re1-wallet-200-20260923` (tip `2b9a0ca9`, off master) from a pinned worktree; add queue-ahead and public-print recording, 40-share constant, optional two-band session, analysis script (journal + 88a + ledger); tests against fakes | ~3-5 days [J] | workstation |
| Dated pre-registration (estimands, size deviation, dates, `N_at` count), owner-signed bytes | not written | workstation drafts, owner signs |
| Rulings R1-R6: resume attended live for this scope; guard; pre-registration; panel avoidance or clarification; wallet; sequencing vs v2 look/parity | open | owner |
| 88a retention for test dates; journal and reader pointed at the new wallet; item 67/330 rows per session | routine | production |

**Earliest feasible start:** 2026-11-16 (clean of every panel, after the v2 look). Owner-accelerated: 2026-11-02 if
`N_req` ≤ 14 and the owner waives sequencing. Code can be ready well before either.

## 6. Attended run script (outline)

1. T−24 h: wallet reader summary shows cash 100.00, zero positions, zero open orders; `portfolio report` exit 0; production
   snapshot.
2. T−40 min (workstation, pinned tip): preflight PASS same commit and UTC date; geoblock `blocked=false` and the home tunnel
   down; heartbeat acknowledged; selection table hashed; `L` + reserve ≤ 100.
3. T−5: owner reads the selection and types `go <6 hex>` [M: DECISION_LOG 2026-09-24]; script posts both legs, freezes the
   prediction hash.
4. Loop: per-minute book, reward record, prints, share; requote inside [1, 3] c, ≤ 4; heartbeat 5 s, stale limit 8 s.
5. **Hard limits inside the test** (session ends with cancel-all and reconcile): any fill (sibling cancelled, lot held);
   reward min > size, rate < 40, max spread < 3 c; one-sided or crossed book; geoblock change; heartbeat stale; foreign open
   order; cash/reserve mismatch against a fresh wallet read; 360 min or 23:50Z; `L` would exceed 100; #180 PAUSE/HALT if
   wired. Owner panic command: cancel-all and reconcile.
6. After: authenticated zero open orders; wallet snapshot; next UTC day: `rewards --date`, rebates, payout link (accrual per
   condition where two conditions share a day); settlement: ledger row, redeem, snapshot; record the session row.

## 7. What we will not learn, and risks

Not learned: `f` to any useful precision; whether informed-v0 pulls work; reward share at 75-100 shares or on same-day
bands; T+1 vs T+2 differences; simultaneous fills beyond cash (Q-13); sealed-lane dead-man behaviour; profitability against
`H` (descriptive only; W6 remains); market reaction to a persistent quoter beyond ~8 sessions.

Risks [J]: a date slipping into a panel (the avoidance rule must be mechanical in the selector); RE-1's live defects (post-read
lag, hung heartbeat, 429s) recurring on branch code; terms flipping mid-session; an accidental owner trade on the wallet (fails
closed, spends a session); owner time (8 × 6 h attended); plaintext `.env` on the workstation (recorded exception); reward
attribution when two conditions share a UTC day; the 40-share deviation weakening the link to the proxies' 75-share quote.
