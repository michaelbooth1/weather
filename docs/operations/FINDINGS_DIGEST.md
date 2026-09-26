# Findings Digest

Status: canonical. Written for LLM agents. Hard cap: 250 lines.

| | |
| --- | --- |
| **Owns** | One-sentence conclusions of everything the project has established or withdrawn. Nothing else. |
| **Read when** | Starting any model, evaluation, market-making, settlement or storage task; before citing a number; before proposing a measurement or reopening a question. |
| **Do not use for** | Today's host or work state ([STATE_OF_PLAY.md](STATE_OF_PLAY.md)); invariants ([AGENT_CONTEXT.md](AGENT_CONTEXT.md)); quoting an interval — open the owning section and its source report first. |
| **Depth lives in** | **EF** = [ESTABLISHED_FINDINGS.md](ESTABLISHED_FINDINGS.md), loaded by section: `Grep` for `^## <id>\.` (or `^### <id>\.` for 10a–10o), then `Read` from that line. **RF** = [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md), entries cited by heading. **HW** = [HOW_WE_GET_THINGS_WRONG.md](HOW_WE_GET_THINGS_WRONG.md). α budget: [CAMPAIGN_LEDGER.md](CAMPAIGN_LEDGER.md). |
| **Next and evidence** | Unanswered: [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md). Audits: [audit index](../roadmap/audits/README.md). Owner decisions by date: [DECISION_LOG.md](DECISION_LOG.md). |

Mission ids such as `-09-56a` are sequence numbers, not calendar dates; September ids exist twice (workstation research lineage 09-01..09-11 vs production missions from 09-21): cite the former as `research 2026-09-NNx` with its branch. Strata: **B** = in-season
pre-boundary panel (23 dates), **C** = out-of-season pre-boundary panel (27 dates); never pooled, and
never pooled across the 2026-07-31 provenance boundary.

## Where the project stands in 12 lines

1. The goal is a better daily-high forecast from our own information for 12 city markets; the end state is market making on International Polymarket. EF §0, §0c.
2. Objective order (owner, 2026-09-23): protect capture and settlement evidence; **pillar A** improve the forecast from our own free information; **pillar B** earn liquidity rewards as a maker, pulling quotes around information arrival. See [the forward plan](forward-plan-2026-09-23.md). EF §0.
3. The model does not beat the market, and the gap is missing information, not calibration. EF §1, §1c.
4. One change has ever improved a served number: the serving floor, 2026-07-31. EF §3.
5. No cell out of 114 pre-registered ones shows a quotable model edge. EF §1b.
6. The declared primary objective (09:00–14:00 local) has no powered measurement; the old ~504-date requirement rested on a retired effect size and is withdrawn, and no replacement figure is citable. EF §1b, §5.
7. No profitability result exists yet: RE-1 has four fills, one paid reward day (+2.13 vs ~2.03 modelled) and three settled lots (net +6.43) — far too little to judge. EF §10m.
8. One attended real-money lifecycle test ran on 2026-09-06 off master with zero fills; it is spent and grants nothing. EF §10f.
9. The configured liquidity-reward pool is two orders of magnitude larger than the figure the economics case used; our share of it is unmeasured. EF §10a.
10. Streak contiguity gates nothing on the critical path; settled, promotion-countable date volume is what counts. EF §0d.
11. Historical replay cannot reproduce what production served; do not commission reproduction work. EF §1k.
12. Owner decisions in force: no live trading (all paused 2026-09-25, including RE-1; see STATE_OF_PLAY), International only, no paid weather APIs, backups deprioritized; **model work unpaused 2026-09-21** (measurement first; a candidate needs a pre-registration before it is scored). Current authority is read from [STATE_OF_PLAY.md](STATE_OF_PLAY.md).

## Model and forecast: what is established

- The served in-season gap to market mid is **1.423246x [1.2426, 1.6590]**; the older clean-regime 1.24x is a different panel and must not be equated with it. EF §1.
- The gap is information-dominated: recalibration is bounded at **16.494%** of the gap and is not distinguishable from zero (the older 98.88% / 1.12% split is retired). EF §1c.
- Shrinking toward the market closes the gap by construction; it locates missing information and is never an improvement or an edge. EF §1c, §5.
- The serving floor moved the served ratio **1.6639 → 1.4980**, crossed CI [−0.3553, −0.0698]; about 2.2% of it landed in the primary window. These numbers are the positive control for any skill tracker. EF §3.
- The cool bias is real (**−0.64387 C-eq** on the current surface), caused by seasonal training coverage, and is not correctable at serve. EF §2.
- The model was blind on 10 of 19 live features all day, fleet-wide; 9 are repaired (two stay dead in Fahrenheit markets by design) and the repair did **not** move the gap — a precise null. EF §4.
- Loss is concentrated: **4.387%** of band rows carry **64.140%** of excess loss. EF §1, §1f.
- That tail is centre overconfidence and is predictable ex ante (AUROC **0.90260**), but conditional reshaping loses to global on its own training score: knowing where the loss is does not make a fix. Distribution reshaping is closed. EF §1f, §1g.
- The centre, not the width, is the lever; never sharpen globally; never weaken the floor. EF §1, §2, §1g.
- The forecast archive covers the wrong days for a retrain, no target-year row is ever in-sample, and the retrain blocks on 14 cells whose floor of 18 is not a knob. EF §4a-bis, §4b, §4c, §4g.
- The free tier offers 12 of the 21 declared point-in-time fields; the other 9 are a real wall, and sourcing them from stitched history would re-create a named contamination defect. EF §0a, §4f.
- The point-in-time source stops at 2026-06-23 in production, so the `-09-58a` null is blind, not precise; the staged 12-field fetch is not adopted (adopting it is a serving change); a sealed copy was the research lineage's 2026 evaluation input. EF §1e, §1m.
- **The 11 extra free PIT fields are tested, not untested** (workstation research lineage, 2026-09-01..04, unmerged): an NWP-anchored residual challenger was `INCONCLUSIVE_UNDERPOWERED` three times (2025 May-Aug +0.2751 C² [−0.0234, 0.6186]; outside-window 2025 +0.0451 [−0.2422, 0.3552]; 2026 no-refit directionally consistent), never harmful; a 12-field pooled-refit replacement worsened the C-pre centre and may not be replicated. The spent evaluations may not be reused. EF §1m.
- Free provider history depth: temperature 2021-2025, ten more fields 2024-2025 only, `precipitation_probability` 2025 only; two research corpora (13.8 M and 11.2 M rows) live only on the workstation. No free source satisfies the v2 point-in-time contract (`NO_GO_PROVIDER_BOUND_AVAILABILITY_AND_PARITY`). EF §1m.
- Training data is contaminated at fit time, and `forecast_high` is not point-in-time. EF §6, §0a.
- `high_so_far` is not a running maximum: the vendor observation series is not append-only, and when it drops rows the input window slides backward (658 of 658 B cutoff changes narrowed). EF §1k (`-09-70a`, `-09-71a`).
- A floor-safe recovery rule exists (recover a row only if the current payload has nothing at or after its minute; zero new above-settlement rows on 28,254 snapshots) but its evaluation is unpowered and the thread is closed. EF §1k (`-09-73a`, `-09-78a`).
- Production served working-tree bytes that were never committed: 324 of 413 captured file fingerprints match no reachable Git blob. EF §1k (`-09-76a`).
- Since live WU inputs were disabled on 2026-06-30, 13 of about 26 serving post-processing stages are no-ops — **code-traced, served output not read**. EF §10e.
- Station guidance is captured, not missing, and the active artifact selects no NBM, NWS-grid or HRRR column. **Measured 2026-09-21 (`-09-79a`, 503 market-days, descriptive):** the gap to the market is already 1.44-1.48x at 06:00-09:59 local; band probabilities read straight off the captured NBM percentiles (no fitted parameter) beat the served model on matched morning snapshots by about 0.012-0.015 Brier in both strata, intervals excluding zero, yet still sit at 1.15-1.22x the market. Conditional on guidance being present (24.6-38.3% fill, none after 10:00, none for Toronto) and 35-40% powered: **a lead, not a candidate result.** Settlement-instrument mismatch is under 3.5%, so rounding is not the story. EF §10h. **`-09-81a` (pre-registered, development): scored on every US morning row with fallback to served, the gain halves to about -0.0067 (C1) / -0.0063 (fixed 50/50 pool), below the frozen minimum-effect threshold; still 1.36x the market. Most guidance is dropped because it sits below the observed floor (fill 73% at 06:00 falling to ~7% at 09:00). Under crossed date x market clustering an effect this size cannot be confirmed at any season length - 11 market clusters cap power near 40%. No reservation.** EF §10j. **`-09-82a` (trace on real NOAA bulletins, no score): the values were for the wrong period. 13Z and 19Z NBP bulletins begin with a 12Z minimum and contain no maximum for the current local date; the parser took that first token, so from 06:00 Pacific / 09:00 Eastern onward we read tomorrow morning's minimum as today's maximum and the floor correctly threw it away (66 of 66 wrong at 13Z/19Z, 99 of 99 right at 01Z/07Z; confirmed live on production). "No guidance after 10:00" was a parser defect.** The served model uses no NBM column, but a live, promotion-blocked shadow variant does, so the repair is a versioned parity change (EF §10k). `-09-83a` built it (PARTIAL): from 12Z onward the newest bulletin holding today's maximum is 07Z, so later guidance is 5-24 hours old by construction. **Production downloads the same ~35 MB national bulletin on almost every market pass (729 downloads, 24.9 GB in 15 hours on 2026-09-21) because the fan-out scope is one supervisor iteration.** `-09-83b` built both the finished repair and fail-open reuse of a held cycle file (fixture probe: 33 downloads to 1); neither is landed. Mission `2026-09-83c` closes the out-of-scope leftovers and delivers three stacked integration branches for host qualification. EF §10l.

## Evaluation and statistics rules that bind every claim

- Crossed date × market clustering is mandatory; exchangeable market-day resampling gives intervals that are too narrow and has retracted headline results. EF §5.
- Report power and MDE with every estimate; a delta not distinguishable from zero is reported in those words. EF §5.
- Cite the bound, never the point: **16.494%**, not 8.829%. EF §1c.
- The primary-slice endpoint has no citable date requirement: ~504 rested on a retired effect size, and a re-derived ~39 is conditional on a point estimate whose interval crosses zero. The pre-boundary panel has 50 dates. EF §1b, §5.
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
- Public execution tape, 30 dates / 377,104 trades (2026-09-20): ~~taker fee 0 on every trade, so rebates zero~~ **(retired 2026-09-24: weather takers pay `shares x 0.05 x p(1-p)` since 2026-03-30, makers pay 0, and 25% of weather taker fees fund maker rebates by filled liquidity; the old zeros were likely a missing field; EF §10o)**; share-weighted maker markout is +0.19 c/share at 5 minutes and -0.43 c to settlement (rebate excluded). Reward-share estimate from captured books: displayed qualifying competition is thin (median modelled share 0.39 for a 20-share quote) - **unconfirmed until one paid reward epoch; `R` was not frozen before the read, so the pre-registered decision rule was not applied.** [Item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md).
- The configured reward pool is about **2,800 per day same-day and 4,800 all active**, stable on 31 of 31 sampled days 2026-08-15..09-19; it is a shared pool, not income; the unit is confirmed by the first paid day (09-24, EF §10m). EF §10a.
- The 10 pUSD per-band cap makes a two-sided 20-share quote (about 19.60 pUSD) reward-ineligible; the July `NOT_VIABLE_CURRENT_TRACK` leg that rests on this is unchanged. EF §10a, `docs/roadmap/agent-report-2026-07-27-workstation-mm-viability.md`.
- Public reward reads, 2026-09-20: the venue publishes a per-condition reward record with a `market_competitiveness` field never captured here (0 on five of eight same-day bands; not our competing Q-score); same-day bands flip from a 20- to a 100-share minimum during the morning, so same-day 20-share estimates are too high; next-day 20-share bands are contested - modelled share 0.01-0.10 in ten of twelve cities, 0.18-0.34 only in Los Angeles. All modelled, none paid. [Item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md), [RE-1 pre-registration](../research/liquidity-reward-epoch-preregistration-2026-09-20.md).
- **RE-1 session 1, 2026-09-23 (first real reward session; one session, one NYC T+2 band, 42 minutes):** the venue's own
  accrual (0.117) and reward percentage (6.23% vs our 5.69%/6.51%) sat between our two competition scenarios (`P_many`
  0.105, `P_single` 0.125) - the share model's scale holds; the YES/NO books mirror (37/42 minutes exact, effect -0.03%).
  **Competition quadrupled within 40 minutes** (qualifying depth 315 -> 1,399 shares at our levels), so the selection-time
  projection (2.45 per 6 h) decayed to ~0.18 cents/minute; whether we caused it is not identifiable. Fill: a taker bought
  25.57 YES at .52 against two NO makers at .48 (20 ahead of our 5.57). Below the 1-dollar minimum: unpaid. Mission 86c
  (`codex/re1-session1-analysis-20260923` @ `b4b97807c`).
- **RE-1 sessions 2-8, 2026-09-24 (75 shares, attempts numbered separately from sessions):** minute-integrated modelled reward
  again matched accrual (0.438 vs 0.352/0.447; 0.376 vs 0.330/0.347); **the first paid day: UTC 09-24 paid +2.13 vs ~2.03
  modelled, k ≈ 1.05**. **Share halved within 2-4 minutes of posting in every session** (Miami 95% -> 3.6%). Four fills, all
  on the thinnest bands; only Miami's 75 YES looks informed (-8.5 c at +5/+30 min); ~43.8 held to settlement. On an empty
  band size and closeness buy no reward, only fill exposure; the owner's amendment now requires existing two-sided depth
  (>= max(75, size)) and local T+1/T+2. EF §10m.
- **Open orders are limited to cash per market, not across markets (owner, replicated 2026-09-24):** 299.00 of resting buys on
  four bands were accepted on 96.15 cash; each weather band is its own market, so the same cash backs many bands, and the risk
  becomes simultaneous fills across markets beyond cash, whose venue handling is unmeasured. EF §10n.
- **Observation clock (89b, 2026-09-23, IEM archive 06-01..09-22, 12 stations):** routine METAR minutes are station-specific
  (modal :51 KORD/KLGA, :52 KATL, :53 seven stations, :56 KSFO, :58 KBKF, :00 CYYZ; each >99.8% on its mode), so
  `info_event_calendar.py`'s fixed :52 is wrong for 11 of 12; SPECI 1.9-5.2/day. A clock-and-running-maximum estimator of
  'band already decided' scores Brier 0.042 on held-out September against 0.24 for a constant (miscalibrated in the
  0.3-0.4 bin); report-to-availability lag is not measurable from the archive. Timing inputs only, no edge claim.
  (`codex/observation-clock-20260923` @ `d059cc78`).
- A current economics snapshot cannot score historical maker runs; each dated condition has its own identities. EF §8k.
- International Stage 0/1 software is adopted on master; the 2026-09-06 attended test ran different, unmerged code; Stage 2 has never run. EF §8t, §10f, [item 67](../roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md).
- Geographic eligibility is recorded as resolved by owner statement (2026-09-19); the operating rule is that the home file-access tunnel is down for a whole live session. [INTERNATIONAL_MM_LIVE_PILOT.md](INTERNATIONAL_MM_LIVE_PILOT.md).
- Release #1 is not sufficient for promotion, and the release machinery is off the critical path. EF §9, §0b.

## Operations and data facts that bite

- Near-close order-book and execution tape cannot be backfilled; a reconnect gap cannot be repaired from the public API. EF §0, RF "A reconnect gap can be backfilled".
- Free disk is a sawtooth and the daily low binds; since 2026-09-23 the low is in the evening (System Restore purges, not tiering) - judge from the trail's 24 h minimum; every reclaim lane refuses at low free space. EF §10b.
- Linked worktrees each smudge about 363 MiB of model pickles already held in `.git/lfs` (about 62 GiB across 175 worktrees at audit time); create worktrees with `GIT_LFS_SKIP_SMUDGE=1`. EF §10b.
- The settlement chain is single-shot, sits behind a learning-lane audit, has no retry and no backfill; each missed date needs an explicit backfill. EF §10d.
- Finalize re-revises every historical market-day on each run because its hash includes wall-clock time; a teardown loses the new day. EF §10d, [FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md](FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md).
- The venue's declared resolution source moved from WU to `weather.gov` timeseries around 2026-08-23; band agreement 921/921 before, 359/360 after (ledger count 2026-09-22, all 360 labelled); current Rules resolve on the page's "Hourly Data"; exact-degree agreement unmeasured (86a UNDECIDABLE; free IEM METAR matched 480/480 pre-switch WU degrees); the code still hard-codes WU. EF §10c.
- The capture host's `data/metar` history store stops at 2026-06-30 (found 2026-09-21; cause not traced); August-September METAR/SPECI must come from the free IEM archive.
- A held maker quote cannot rely on the dead-man alone: venue cancel-on-disconnect is 10-15 s, so explicit acknowledged cancel is primary; master's isolated-wallet control needs a fresh wallet (the 2026-09-06 wallet held 275-490 pUSD). EF §10i.
- The memory-guard kill path was inert 2026-08-23 -> 2026-09-20 00:38; the fix is on master since. EF §10g.
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
| A better free point-in-time source under the v2 contract | No provider documents historical first-availability; no archive/forward parity | EF §1m (research `2026-09-82a`) |
| 12-field pooled-refit replacement on the sealed panel | Centre worse, Brier null, its own rule forbids replication | EF §1m (research `2026-09-86a`) |

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
