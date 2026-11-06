# Edge trial charter

Status: master ruling 2026-11-05 22:20 ET. Owner basis: DL 2026-11-05 ~21:04 (deadline) and ~21:50 (definition); plan approved ~22:05 ("approved full plan").

## 1. What counts as edge
Edge is **positive net profit in an accurately simulated environment, shown by a fair trial** (owner, 11-05). Market making and simulated reward profit count. A Brier or log-score win (B, MG-1, any screen) is a diagnostic, never edge on its own.

## 2. Accurate simulation: minimum standard
Every trial's simulator must meet all of the following.
1. **Prices.** Executable prices come from the captured CLOB books: best bid and ask, and depth by level, at the decision time. The Gamma display price (`market_yes`) is never an execution price.
2. **Latency.** Decision time is no earlier than the time of our input data, plus our measured end-to-end latency (p95 or worse). An order sees no book state earlier than that.
3. **Taker costs.**
   - Fee: 0.05·p(1−p) per share.
   - Slippage: at least 1 c, or walk the captured depth, whichever is worse.
   - Size: capped at the displayed depth.
4. **Maker economics.**
   - Fee: 0.
   - Rebates: our fee-weighted share of the 25% weather rebate pool.
   - Rewards: the venue's liquidity-reward scoring of our resting orders against the competing captured book, with that day's per-condition rates, minimum sizes and maximum spreads. Where a day's configuration was not captured, the prereg names the substitute rule in advance and discloses it.
   - Fills: we are assumed to be at the back of the queue at our price, and a fill needs traded volume through our level on the execution tape.
   - Adverse selection: the informed-fill fraction *f* is a pre-declared conservative value (or range), never fitted on trial dates.
5. **Capital.** The owner's real limits apply, per market and in total. Cash is limited per market (EF §10n). Minimum sizes must be met, or the order earns no reward.
6. **Settlement.** Settlement is on the venue's actual resolution (the winning market), never our reconstructed label.
7. **Accuracy gate.**
   - **Maker trials:** before any PASS counts, the simulator replays our own live pilot sessions. It must match the paid rewards, our fills and our markouts within tolerances pre-declared in its prereg. A failed gate means the trial cannot PASS; it is reported as such.
   - **Taker trials:** these rest on book-capture fidelity and the latency rule. The prereg states its capture-gap rule.

## 3. Fair trial: minimum standard
1. **Frozen first.** The prereg states the strategy, simulator and scoring code (sha-pinned), the trial dates, the PASS rule and the looks. It is frozen and its sha recorded before any read of the trial dates.
2. **Out-of-sample dates.** Trial dates are either forward, or captured but unread. Dev dates (≤ 09-29), the released 09-30..10-14 window and any date already read can only kill or describe.
3. **PASS rule.** The one-sided lower bound of mean net P&L per pre-declared unit (market-day or trading day) is above 0, at the trial's α share, using date-clustered resampling with the block length pre-declared. The point estimate must also meet the prereg's stated economic minimum.
4. **Looks.**
   - One look, or pre-declared sequential looks with an α split (e.g. look 1 at 20% of the trial's α).
   - No peeking.
   - No re-cut after a read.
   - No changes to a frozen trial; a clarification is dated and outcome-blind.
5. **Multiplicity.**
   - The family is every profit trial registered under this charter, numbered T1, T2, ...
   - Family-wise one-sided α is 0.05, with Holm's procedure applied at 12-28 over every trial's final p-value.
   - A trial added later joins the family. Its α share is set at its freeze.
6. **Dates shared with other tests.** A trial frozen before any read may share dates with B, MG-1 or F8-MH (owner 11-05). It never changes their rules, and reading prices or outcomes for it never feeds back into them.
7. **Records.** Every trial keeps its prereg sha, input manifests, outputs and a receipt. Every kill goes to EXHAUSTION_REGISTER §6 and the never-cleaned archive (rule 13).
8. **Deadline.** Each trial's final look must fall on or before 12-28, so that a verdict package exists by 12-31.

## 4. Registered trials (update as each freezes)
| Trial | Route | Status | Trial dates | Looks | α share |
| --- | --- | --- | --- | --- | --- |
| T1 | Market-centred post-only maker (no model) | Feasibility WS-1, gate G1 11-12 | captured unread 10-15..~11-15, then forward to ~12-24 | look 1 ~11-20..25; final ~12-27 | at freeze |
| T2 | Paper taker on bound MG-2 as-of vectors | Rule built as one module with the early warning WS-3 | 10-29..12-12, under its own outcome-blind date rule | ~12-15 | at freeze |
| T3 | Ladder (negRisk) structural arbitrage | Only if the dev scan WS-2 finds executable cases | forward from freeze | ~12-20 | at freeze |
| T4+ | Paper taker on a model candidate that passes a dev screen by ~11-15 | — | forward, D0 ≤ 11-20 | ≤ 12-28 | at freeze |

## 5. Not changed by this charter
- B (Rule B-1) and MG-1 stay as bound. Their verdicts are reported as diagnostics.
- No agent places, cancels or signs orders.
- Live sessions are started by the owner. Live orders need an explicit owner request and the readiness and release gates.
- International Polymarket is the only trading venue.
- Paid data needs a per-source owner approval.
