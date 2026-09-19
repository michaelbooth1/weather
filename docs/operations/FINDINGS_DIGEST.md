# Findings Digest

Status: canonical. Written for LLM agents. Hard cap: 250 lines.

| | |
| --- | --- |
| **Owns** | One-sentence conclusions of everything the project has established or withdrawn. Nothing else. |
| **Read when** | Starting any model, evaluation, market-making, settlement or storage task; before citing a number; before proposing a measurement or reopening a question. |
| **Do not use for** | Today's host or work state ([STATE_OF_PLAY.md](STATE_OF_PLAY.md)); invariants ([AGENT_CONTEXT.md](AGENT_CONTEXT.md)); quoting an interval — open the owning section and its source report first. |
| **Depth lives in** | **EF** = [ESTABLISHED_FINDINGS.md](ESTABLISHED_FINDINGS.md), loaded by section: `Grep` for `^## <id>\.` (or `^### <id>\.` for 10a–10g), then `Read` from that line. **RF** = [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md), entries cited by heading. **HW** = [HOW_WE_GET_THINGS_WRONG.md](HOW_WE_GET_THINGS_WRONG.md). α budget: [CAMPAIGN_LEDGER.md](CAMPAIGN_LEDGER.md). |

Mission ids such as `-09-56a` are sequence numbers, not calendar dates. Strata: **B** = in-season
pre-boundary panel (23 dates), **C** = out-of-season pre-boundary panel (27 dates); never pooled, and
never pooled across the 2026-07-31 provenance boundary.

## Where the project stands in 12 lines

1. The goal is a better daily-high forecast from our own information for 12 city markets; the end state is market making on International Polymarket. EF §0, §0c.
2. Objective order: protect capture and settlement evidence; decide whether International market making pays after every cost; then improve the forecast. EF §0.
3. The model does not beat the market, and the gap is missing information, not calibration. EF §1, §1c.
4. One change has ever improved a served number: the serving floor, 2026-07-31. EF §3.
5. No cell out of 114 pre-registered ones shows a quotable model edge. EF §1b.
6. The declared primary objective (09:00–14:00 local) cannot be measured at any sample size we can reach soon. EF §1b, §5.
7. No profitability result exists: no fill, fee, rebate, reward or P&L has ever been observed on our account. EF §0, §8c.
8. One attended real-money lifecycle test ran on 2026-09-06 off master with zero fills; it is spent and grants nothing. EF §10f.
9. The configured liquidity-reward pool is two orders of magnitude larger than the figure the economics case used; our share of it is unmeasured. EF §10a.
10. Streak contiguity gates nothing on the critical path; settled, promotion-countable date volume is what counts. EF §0d.
11. Historical replay cannot reproduce what production served; do not commission reproduction work. EF §1k.
12. Owner decisions in force: no live trading, International only, no paid weather APIs, no new model-alpha work for now, backups deprioritized. Current authority is read from [STATE_OF_PLAY.md](STATE_OF_PLAY.md).

## Model and forecast: what is established

- The served in-season gap to market mid is **1.423246x [1.2426, 1.6590]**; the older clean-regime 1.24x is a different panel and must not be equated with it. EF §1.
- The gap is 98.88% resolution and 1.12% reliability: recalibration is bounded at **16.494%** of the gap and is not distinguishable from zero. EF §1c.
- Shrinking toward the market closes the gap by construction; it locates missing information and is never an improvement or an edge. EF §1c, §5.
- The serving floor moved the served ratio **1.6639 → 1.4980**, crossed CI [−0.3553, −0.0698]; about 2.2% of it landed in the primary window. These numbers are the positive control for any skill tracker. EF §3.
- The cool bias is real (**−0.64387 C-eq** on the current surface), caused by seasonal training coverage, and is not correctable at serve. EF §2.
- The model was blind on 10 of 19 live features all day, fleet-wide; 9 are repaired (two stay dead in Fahrenheit markets by design) and the repair did **not** move the gap — a precise null. EF §4.
- Loss is concentrated: **4.387%** of band rows carry **64.140%** of excess loss. EF §1, §1f.
- That tail is centre overconfidence and is predictable ex ante (AUROC **0.90260**), but conditional reshaping loses to global on its own training score: knowing where the loss is does not make a fix. Distribution reshaping is closed. EF §1f, §1g.
- The centre, not the width, is the lever; never sharpen globally; never weaken the floor. EF §1, §2, §1g.
- The forecast archive covers the wrong days for a retrain, no target-year row is ever in-sample, and the retrain blocks on 14 cells whose floor of 18 is not a knob. EF §4a-bis, §4b, §4c, §4g.
- The free tier offers 12 of the 21 declared point-in-time fields; the other 9 are a real wall, and sourcing them from stitched history would re-create a named contamination defect. EF §0a, §4f.
- The point-in-time source stops at 2026-06-23, so the `-09-58a` null is blind, not precise; the staged fetch is not adopted and adopting it is a serving change. EF §1e.
- Training data is contaminated at fit time, and `forecast_high` is not point-in-time. EF §6, §0a.
- `high_so_far` is not a running maximum: the vendor observation series is not append-only, and when it drops rows the input window slides backward (658 of 658 B cutoff changes narrowed). EF §1k (`-09-70a`, `-09-71a`).
- A floor-safe recovery rule exists (recover a row only if the current payload has nothing at or after its minute; zero new above-settlement rows on 28,254 snapshots) but its evaluation is unpowered and the thread is closed. EF §1k (`-09-73a`, `-09-78a`).
- Production served working-tree bytes that were never committed: 324 of 413 captured file fingerprints match no reachable Git blob. EF §1k (`-09-76a`).
- Since live WU inputs were disabled on 2026-06-30, 13 of about 26 serving post-processing stages are no-ops — **code-traced, served output not read**. EF §10e.

## Evaluation and statistics rules that bind every claim

- Crossed date × market clustering is mandatory; exchangeable market-day resampling gives intervals that are too narrow and has retracted headline results. EF §5.
- Report power and MDE with every estimate; a delta not distinguishable from zero is reported in those words. EF §5.
- Cite the bound, never the point: **16.494%**, not 8.829%. EF §1c.
- The primary-slice endpoint needs about **504 dates**; the pre-boundary panel has 50. EF §1b, §5.
- The panel has a hard MDE floor of about **3.2%** of the gap set by the 12 market clusters, not by dates; improvements below it must be batched. EF §1d.
- α = 0.0025 per decision is nominal; on the thin tail the delivered rate was short, so quantile `q = 3.1098893` (amendment A1) applies to any future decision on the panel. EF §1i, [CAMPAIGN_LEDGER.md](CAMPAIGN_LEDGER.md).
- The α ledger is binding: 20 decisions, pre-register the row before scoring, never renumber; read the spend from [CAMPAIGN_LEDGER.md](CAMPAIGN_LEDGER.md), not from a copy.
- Check that a look has power **before** spending α, on the actual estimand, with both decision branches reachable. EF §1k (`-09-77a`, `-09-78a`).
- A fail-on-any-row gate is a panel-size limit, not a quality bar; never re-register Gate 3 unchanged. EF §1j, §1k (`-09-68a`).
- Score any fitted mapping on its own training set before reading its test result. EF §5.
- The admission bar is `promotion_countable`, not `quality_grade == "complete"`; there are 34 date clusters, not 5. EF §5, RF "The 5-date window was a convention".
- Settlement authority is `data/settlements/<market>/ledger.jsonl`, never `market_day_labels.csv`; ledger rows are not market-days. EF §5, RF "Ledger rows are NOT market-days".
- Never pool across the 2026-07-31 boundary: it is artifact provenance (commit `b77cfbed`), not a date cutoff. EF §5, RF "`2026-07-31` is not a date cutoff".
- The instrument was audited and is sound where it matters: the repair adds no zeros, the served floor is cosmetic in the mean, and the labels are flat (label-effect ceiling about 13% of the gap). EF §1k (`-09-64a`..`-09-67a`).
- Replay floors are rebuilt, not recorded: the raw replay floor exceeds the settled high on 7.478% of rows against 0.008% for the served floor, and divergence is confined to B. [REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md](REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md).
- A grep is not a trace: trace one instance end to end before publishing a structural claim. EF §7, §9, HW Pattern 4.
- Unsettled dates silently leave every scorecard, and evaluators fall back to a tape-derived proxy label when the ledger has no row; the promotion path does not. EF §10d.

## Market making and economics

- The approved experiment is market-centred, backed, post-only resting liquidity: spread plus paid rebates plus paid rewards against adverse selection, inventory loss, fees and operating cost. EF §0, [item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md).
- Under the promotion gate the maker could not quote market-centred at all; the model-independent `market_harvest` lane exists for that reason. EF §8bb, §8q.
- A "countable day" never required a quote and `fills.jsonl` was never written: the maker clock counted eligibility, not outcome. EF §8b, HW Pattern 2.
- A zero-edge maker breaks even across a wide scenario range, and viability is dominated by the informed-fill fraction `f`, which is **unidentified**, not underpowered. EF §1b.
- Executions cannot be reconstructed from book capture; public execution capture (pilot 2026-08-10, supervised since 2026-08-15) gives price paths and counterfactual markouts only. EF §1b, §8c.
- Only authoritative own-account events, balances and payout receipts prove realized economics. EF §8c, RF "Forward public execution capture is the only route".
- The public execution tape has no analytical consumer yet; two studies were authored on 2026-09-19 (markout, reward share) and are **unexecuted**. [Item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md).
- The configured reward pool is about **2,800 per day same-day and 4,800 all active**, stable on 31 of 31 sampled days 2026-08-15..09-19; it is a shared pool, not income, the share is unmeasured, and the unit is unconfirmed by any paid epoch. EF §10a.
- The 10 pUSD per-band cap makes a two-sided 20-share quote (about 19.60 pUSD) reward-ineligible; the July `NOT_VIABLE_CURRENT_TRACK` leg that rests on this is unchanged. EF §10a, `docs/roadmap/agent-report-2026-07-27-workstation-mm-viability.md`.
- Whether taker fees — and therefore maker rebates — are non-zero on these markets is open: sampled tape rows on 2026-09-19 carried `fee_rate_bps: "0"`, unverified at scale. [MARKET_MAKING_PLAN.md](../research/MARKET_MAKING_PLAN.md) Part 0.
- A current economics snapshot cannot score historical maker runs; each dated condition has its own identities. EF §8k.
- International Stage 0/1 software is adopted on master; the 2026-09-06 attended test ran different, unmerged code; Stage 2 has never run. EF §8t, §10f, [item 67](../roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md).
- Geographic eligibility is recorded as resolved by owner statement (2026-09-19); the operating rule is that the home file-access tunnel is down for a whole live session. [INTERNATIONAL_MM_LIVE_PILOT.md](INTERNATIONAL_MM_LIVE_PILOT.md).
- Release #1 is not sufficient for promotion, and the release machinery is off the critical path. EF §9, §0b.

## Operations and data facts that bite

- Near-close order-book and execution tape cannot be backfilled; a reconnect gap cannot be repaired from the public API. EF §0, RF "A reconnect gap can be backfilled".
- Free disk is a daily sawtooth with its low near 04:50; the daily low binds, and every reclaim lane refuses at low free space. EF §10b.
- Linked worktrees each smudge about 363 MiB of model pickles already held in `.git/lfs` (about 62 GiB across 175 worktrees at audit time); create worktrees with `GIT_LFS_SKIP_SMUDGE=1`. EF §10b.
- The settlement chain is single-shot, sits behind a learning-lane audit, has no retry and no backfill; each missed date needs an explicit backfill. EF §10d.
- Finalize re-revises every historical market-day on each run because its hash includes wall-clock time; a teardown loses the new day. EF §10d, [FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md](FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md).
- The venue's declared resolution source moved from WU to `weather.gov` timeseries around 2026-08-23; band agreement 921/921 before, 131/132 after; exact-degree agreement unmeasured; the code still hard-codes WU. EF §10c.
- The memory-guard kill path has been inert since 2026-08-23; the fix is authored and not adopted. EF §10g.
- Read-only is not the same as safe on the capture host: abandoned agent tool calls keep running, and that load caused the 2026-08-23 incident. EF §8u, [HOST_LOAD_POLICY.md](HOST_LOAD_POLICY.md).
- Reopening a large live log took capture down for 5 h 54 m; rotation is bounded and non-deleting. EF §8e.
- A terminated scheduled wrapper can leave its governed child alive; a DEAD status with a source closure is a tombstone; PID alone does not prove lock ownership. EF §8d, §8g, RF "A live PID proves it still owns an old lock".
- Scheduler exit 0 does not mean work happened (busy-lease skips are non-fatal), and two tasks exit non-zero daily by design. RF "Tiering task 0x0", RF "Two scheduled tasks exit non-zero".
- A reboot does not kill the fleet. RF "A reboot kills the fleet".
- Commits that touch a module inside a capture loop's import closure roll capture; the `SOURCE_PATTERNS` glob is not the test. RF "The `SOURCE_PATTERNS` glob".
- Agent reports and code exist only on unmerged branches: never delete a branch ref; branch names mislead, so read the commits. RF "Agent reports exist only on unmerged branches", "Branch names lie".
- Master does not describe everything production ran: the 2026-09-06 live test and other lanes executed from unmerged code. EF §10f; current reconciliation in [STATE_OF_PLAY.md](STATE_OF_PLAY.md).

## Closed threads — do not reopen

| Thread | One-line reason | Pointer |
| --- | --- | --- |
| Historical reproduction of served output | Exactly reconstructable: 0 of 368 decision rows, 111 of 28,254 B rows; the bytes were never committed | EF §1k; [trace](REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md) |
| Observation-recovery candidate | Floor-safe but unpowered: MDE 0.1571 exceeds the most favourable effect 0.1385; α kept | EF §1k (`-09-78a`) |
| Instrument audit (zeros, floor, labels) | Checked one by one, no α spent, the gap is real | EF §1k |
| Recalibration / global sharpening | Bounded at 16.494% of the gap, interval includes zero | EF §1c |
| Conditional distribution reshaping | Lost to global on its own training score | EF §1g |
| Searching for a quotable model edge | 114 cells, zero positive | EF §1b |
| Input repair as the gap explanation | Precise null: in-season ratio moved 1.423260 → 1.423246 | EF §4 |
| Retrain / release machinery as the critical path | Owner decision 2026-08-09; terminal blocker is a genuine free-tier wall | EF §0a, §0b |
| Streak contiguity as an objective | Owner challenge upheld 2026-08-10; 7-day shelf life | EF §0d |
| Decision 10 (PIT field test) | Closed unused, number retired, never reassign | EF §1j; ledger |
| Paid weather providers; Polymarket US | Owner decisions | [AGENT_CONTEXT.md](AGENT_CONTEXT.md) |
| Geographic eligibility of the execution PC | Resolved by owner statement 2026-09-19; keep the tunnel-down preflight rule | [Pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md) |
| Age-curve explanation of the cool bias; blindness as the centre mechanism | Both rejected by measurement | RF §1 |

## Retracted numbers — never cite

| Number or claim | What replaced it | Pointer |
| --- | --- | --- |
| 24.69% absorption; 5.39% | 18.32% served | RF §1 |
| "78% absorption leak" | Never existed: mismatched denominators | RF §1 |
| "The gap is 1.7x" | 1.24x on the clean regime (older panel); 1.423246x current in-season | RF §1; EF §1 |
| 74.97% centre oracle ceiling | Unciteable; **no replacement exists** | EF §1 |
| −0.6641 C-eq cool bias | −0.64387 C-eq on the current surface | EF §2 |
| 4.26% / 60.2% severity tail | 4.387% / 64.140% | EF §1 |
| 8.829% "recoverable by calibration" as a headline | The bound: at most 16.494%, may be zero | EF §1c |
| 1.017% served realized-band zeros | 8.486% before commit `28d1c146` (2026-06-15), 0.000% after; the pooled rate straddles the fix | [trace](SERVED_BAND_FLOOR_DEFECT_2026-08-10.md) |
| Denver 2026-06-08 "served 0.0 on the winner"; "28 zeros" or "3 zeros" in B | Served 0.5206; two real served-floor crossings in B | EF §1j, §1k |
| 1.5069% label share of the gap | The interval: about 13% ceiling | EF §1k (`-09-67a`) |
| "The incumbent reproduces recorded output" | One Austin market-day at diagnostic grade; Toronto fails at L1 0.00702 | EF §1k (`-09-74a`) |
| 0.4720 / 0.6423 "repair ceiling" as a benefit | Bounds cost, not benefit; superseded by the `-09-78a` NO-GO | EF §1k |
| "Liquidity rewards are about $16 per day, a subsidy not a business" | True for 2026-06-13 only; configured pool about 2,800–4,800 per day since at least 2026-08-15; share unmeasured | RF §4a; EF §10a |
| "Disk headroom is about 4 days" | Instantaneous reading over a same-clock slope; the daily low binds | RF §3; EF §10b |
| "Low disk directly blocks the settlement chain" | No disk gate on that path; indirect route via the commit limit is plausible and unproven | RF §3; EF §10d |
| item 224's win over the market | Leakage | RF §1 |

## Update this file when

A section is added to or superseded in [ESTABLISHED_FINDINGS.md](ESTABLISHED_FINDINGS.md), an entry is
added to [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md), or a thread is closed — in the
same change. One sentence per conclusion, a number only when it is a durable measured result, and a
pointer. No narrative, no history, no current state. If this file would pass 250 lines, merge or drop
bullets; never move depth in here.
