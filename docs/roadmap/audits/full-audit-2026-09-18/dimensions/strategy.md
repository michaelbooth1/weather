# Audit dimension: Goals versus reality and strategic coherence (key: strategy)

Audit date: 2026-09-18. Auditor: one read-only agent on the production capture host.
No project file was modified. Tools used: Read, Grep, Glob (all with explicit paths under
`docs/`, `src/`, `scripts/`, `tools/`), whitelisted `git log / show / branch / ls-tree`, and
non-recursive `ls` of `docs/roadmap`, `docs/roadmap/items`, `docs/roadmap/tracks`, `C:/tmp`.
No python, no tests, no network, no `data/` access.

Health grade for this dimension: **D**.
The project's epistemics are excellent; its strategy is stuck. There is no executable path from
the current state to a go/no-go decision on viability, and the project's own evidence is negative
or null on both routes to its goal.

---

## 1. Scope and method

Read in full or in the relevant part:

- `README.md` (1-200), `docs/operations/STATE_OF_PLAY.md` (all), `docs/operations/AGENT_CONTEXT.md` (all)
- `docs/operations/ESTABLISHED_FINDINGS.md` lines 1-1150, 1750-1810, 1857-2100, 2384-2530, 2700-2754 (of 2754)
- `docs/operations/RETRACTED_AND_FALSE_LEADS.md` (headings + 297-376)
- `docs/operations/HOW_WE_GET_THINGS_WRONG.md` (all), `docs/operations/CAMPAIGN_LEDGER.md` (1-120)
- `docs/operations/OPERATIONS_AGENT_ROLE.md` (225-357), `docs/operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md` (1-70)
- `docs/roadmap/items/item-330-maker-economics-refocus-master-plan.md` (all 811 lines)
- `docs/roadmap/items/item-67-...md` (1-80, 663-704), `item-326-...md` (1-70), `docs/roadmap/active-backlog.md` (all)
- `docs/research/MARKET_MAKING_PLAN.md` (1-300, 380-490), `docs/research/INTERNATIONAL_MM_PILOT_PREREGISTRATION.md` (all)
- `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` (1-110), `PORTABLE_LIVE_EXECUTION_HOST.md` (1-110), `maker-incentive-feasibility.md` (all)
- `docs/roadmap/agent-report-2026-07-27-workstation-mm-viability.md` (1-60, 296-375, 480-520)
- Code traces: `scripts/ops/bounded_worktree_test_suite.ps1` (270-330), `scripts/ops/integration_attempt_suite.ps1` (grep),
  `src/weather/market/mm_paper_scoring.py` (1227-1525, 2200-2280), `src/weather/market/execution_tape_store.py` (grep),
  `src/weather/reporting/market/operator_control_room.py` (grep), `scripts/ops/streak_status.py` (80-150)
- Git: last ~200 master commit subjects; commits `8739902fe`, `f2722a4ed`, `25054ae32`, `2d50bcb09`;
  `STATE_OF_PLAY.md`, item 330 and `maker-opportunity-report.md` as they exist on
  `origin/codex/48h-maker-integration-20260912`; the 12-field seasonal challenger report at `f2722a4ed`.

Live-state numbers (disk 21 GB free, ~5.9 GB/day, 10 of 14 dates unsettled, streak 2/14, qualification
attempts a1..a11 failed, storage-recovery tasks failed 09-14..09-17) come from the lead auditor's reading of
`data/alerts/MORNING_BRIEFING.md`. I did not open `data/`; those numbers are labelled "live state via lead".

---

## 2. Answers to the seven brief questions

### Q1. What are the goals and success criteria, in the owner's terms? Are they measurable? Is anything measuring the OUTCOME?

Owner statements recorded in canon:

- 2026-08-09: "I think the goal should be a better one. I am happy making small improvements at a time until we hit our goal." (`ESTABLISHED_FINDINGS.md:104-105`)
- 2026-08-09: "We should always aim for a better forecast which in time should lead to a tradeable edge somewhere." (`:142-143`), declared "the standing goal of the project ... the ordering rule for every future decision" (`:145-146`).
- 2026-08-10: "I thought the streak would have been worth more but we hit 14 days and it bought us very little." (`:196-197`)
- 2026-08-13: maker-rebate pivot; minimal real-world test authorized with a 100 USDC-equivalent cap (`:2031-2036`). Objectives re-ordered: (1) protect capture/settlement, (2) determine whether International market making is profitable after every cost, (3) improve the forecast from own information (`:22-39`).
- 2026-09-04: refocus on "maker economics plus liquidity rewards", with "no live trading" (`item-330:64-66, 107-117`).
- 2026-09-13 `STATE_OF_PLAY.md:9-12`: objectives are protect evidence, restore reliable unattended execution, execute the non-live maker refocus. "No market edge or profitable maker opportunity is proved."

Measurability:

- Forecast: measurable in principle (served Brier ratio vs market mid, crossed date x market clustering). Parity is 1.0x; measured 1.4232x in-season and 1.526-1.542x out-of-season, the stratum actually served (`:265`, `:498-501`). But the declared primary objective (09:00-14:00 slice) needs ~504 dates against 50 held (`:330-341`), and the 12-market panel has a structural MDE floor of ~3.2% of the gap that no date count removes (`:616-620`). The smallest individually confirmable step is ~5% of the gap, from 2026-10-16 if the post-boundary panel reaches D=73 (`:622-624`, `:649-651`).
- Maker: the primary endpoint is well defined (after-cost cash result, item-330:449-453; preregistration:46-50). The hurdle H ("minimum worthwhile return") is explicitly undefined until W7 freeze (`item-330:631`). Every gate that would measure it (G2-G4) needs live sessions that are not authorized (`item-330:694`).

Is anything measuring the outcome? Essentially no.

- The status headline is still the contiguous clean-capture streak (25 references in `scripts/ops/status.ps1`; `scripts/ops/streak_status.py:94-114` computes a contiguous complete run), which canon itself declared "gates nothing" on 2026-08-10 and contrasted with the real clock: "the metric that matters has no counter at all" (`ESTABLISHED_FINDINGS.md:238-242`). I found no counter of post-boundary promotion-countable date clusters anywhere under `scripts/ops` or `src/weather` (grep for `promotion_countable|countable_date|date_clusters|post_boundary|confirmation_panel`: one code comment only).
- Maker outcome artifacts are empty by construction: "no trade has ever been made and `fills.jsonl` has never been written" (`:152`); the countable-day clock "does not require a quote" (`:1871-1878`); every one of 554,004 post-boundary intent rows was `NO_QUOTE` (`:1911-1913`).
- The project named this itself: "We are excellent at measuring whether we were allowed to do the thing, and we have never once measured whether the thing happened" (`HOW_WE_GET_THINGS_WRONG.md:167-168`). That was written 2026-08-09. It is still true on 2026-09-18.

### Q2. What does the project's own evidence say about reachability?

Forecast edge over the market: **not supported, and the last own-information lever returned a null.**

- "We do not beat the market ... the central finding of the project" (`:258-261`). 114 pre-declared cells, zero with a positive point estimate; overall edge -0.01915 [-0.02444, -0.01443]; "We match the market only where we already agree with it" (`:348-366`).
- Calibration is bounded at 16.494% of the gap and indistinguishable from zero (`:533-541`). Distribution reshaping closed (`:866-873`). Inputs were not the gap (precise null, `-09-44a`).
- The one candidate that "would constitute real edge", a new PIT own-information feature, was "unidentified" (`:640-643`). It has since been run, on an unmerged workstation branch: report `agent-report-2026-09-10-workstation-12field-seasonal-challenger.md` at commit `f2722a4ed` (branch `origin/codex/workstation-collect-multiyear-pit-research-2026-09-87a`). Verdict `INCONCLUSIVE_UNDERPOWERED`: primary Brier delta -0.000555 [-0.004691, +0.003748], power 0.058; centre SSE worsened; every interval spans zero; "the original decision rule therefore does not permit a second research replication". In that report's C-pre table the clean PIT refit scores Brier 0.0779 (baseline) and 0.0774 (12-field) against market 0.0389 and incumbent 0.0601; modal-hit 31-33% against market 64.9%.
- Replay cannot reproduce what was served (114/358 = 31.84% bit-exact; `REPLAY_DOES_NOT_REPRODUCE...:14-19`), which blocks further alpha-spending looks on the sealed panel.
- The project's own summary: "nearly every lever is closed ... The remaining lever is knowing MORE" (`OPERATIONS_AGENT_ROLE.md:240-255`), with no free PIT source left untested that is known to me.

Maker economics: **not supported; first-order arithmetic is unfavourable at the authorised envelope.**

- 2026-06-12 founding plan, measured live: reward budgets "~$1.00/day per event ... Fleet total: ~$16/day. Conclusion: liquidity rewards are a subsidy, not a business" (`MARKET_MAKING_PLAN.md:100-108`). The "actual prize" was trading P&L from a model "better-calibrated than the market in specific windows" (`:128-136`), which `-09-46a` later retired (`ESTABLISHED_FINDINGS.md:365-366`).
- 2026-07-27 pre-declared, adversarially reviewed workstation report: "`NOT_VIABLE_CURRENT_TRACK` - close the market-making track" (`agent-report-2026-07-27-workstation-mm-viability.md:5`). Ground 1: the smallest reward-qualifying two-sided size needs $19.60 against the $10 band cap (`:249-255`). Rebate per 20-share fill at p=0.5 is $0.0625; a full one-sided settlement loss is ~160x that (`:337-346`). Handback: do not spend engineering effort "unless the operator deliberately reopens it with a new risk envelope and a predeclared reason to believe reward dollars can cover passive-fill toxicity" (`:513-516`).
- The risk envelope has not changed (100 pUSD wallet, 10 pUSD band, 25 event, `INTERNATIONAL_MM_LIVE_PILOT.md:76-83`). On 2026-09-11 the unmerged maker branch re-derived ground 1: "Each simultaneous pair breaches the 10 pUSD per-order planning ceiling on one leg", verdict `EVIDENCE_BLOCKED` (item 330 on `origin/codex/48h-maker-integration-20260912`).
- What keeps the track open is a sensitivity grid: zero model edge breaks even in 45.94% of 21,000 scenarios at $0 reward, "dominated by `f`, which is unmeasured ... `f` is now the single most decisive unmeasured number in the project" (`:378-398`). `f` and `A` remain unmeasured.
- Live plumbing: an attended Stage 0/1 lifecycle (two real post-only 5-share orders at 0.001, both cancelled, zero fills) passed on 2026-09-06/07 per commit `8739902fe`. That is recorded only on unmerged branches (see finding strategy-4). It is lifecycle evidence, not economics.

Bottom line: by the project's own records there is no positive evidence for either route, a decision-grade negative for the maker at the current envelope, and a fresh null on the last own-information forecast lever.

### Q3. Is the ordered critical path the shortest path to a viability decision?

No. `STATE_OF_PLAY.md:42-58` lists six steps: (1) qualify the reliability repair with the complete Windows host suite, (2) keep tiering windows clear, (3) publish the documentation reconciliation and complete the documentation transaction, (4) reconcile and qualify the cumulative maker candidate, (5) prove and repair historical settlement omissions, (6) complete W3/G1 provenance and W4 payment semantics.

- None of the six produces forecast-outcome or economic-outcome evidence. Steps 1-4 qualify and merge code and documents. Step 6 resolves evidence provenance for a desk calculator whose current output is `EVIDENCE_BLOCKED`.
- Step 1 is inadmissible right now. The guarded suite path (`scripts/ops/integration_attempt_suite.ps1:168`) runs `bounded_worktree_test_suite.ps1`, which throws below 53,687,091,200 bytes free on any involved volume (`:288-311`, called at `:365` and `:608`); canon confirms "Ordinary qualification retains its 50 GiB disk floor" (`STATE_OF_PLAY.md:24`). Live state via lead: 21 GB free, filling ~5.9 GB/day. Step 4 is explicitly "after reliability acceptance". Archive uploads are owner-paused (`:21`) and the path contains no storage step.
- The only irreplaceable, time-sensitive asset (daily capture plus settled countable dates feeding the D=73 confirmation clock) is ranked fifth, while live state via lead shows 10 of the last 14 dates unsettled.

Cheapest decisive experiments not being run (all non-live, all from data already on disk):

1. **Reward-dollar ceiling.** Sum the configured daily reward rates for weather conditions from the 2026-09-11 public capture (352 conditions, 136 positive allocations, `item-330:51-56`). The rates are captured (`exchange_economics.py` carries the daily-rate fields) but no canonical doc states the dollar total. A configured rate is not a receivable, but it is an upper bound. If the fleet total is still of order $16/day shared with competitors, the "liquidity rewards" half of item 330 is bounded below any plausible hurdle in an hour, without W3/W4 provenance work.
2. **Maker-side markout from the public execution tape.** The tape has run since 2026-08-15 (`item-326:66-70`) and canon says it supports "counterfactual markouts" (`ESTABLISHED_FINDINGS.md:1964`). Nothing reads it. On master the only importers of `execution_tape_store` are the producer, its supervisor and the schema registry; the Control Room reads only health status (`operator_control_room.py:212-216`); the paper fill simulator reads `trades_long.csv`, `market_trades.csv`, `market_ws.jsonl`, `market_ws_events.csv` (`mm_paper_scoring.py:1486-1505`) and not the `execution_tape/` folder the producer writes (`execution_tape_store.py:564`); no code in `src/weather` writes the first two files. The same is true on the cumulative maker candidate branch. Every public trade has a resting maker on the other side; signed post-trade drift at +1m/+5m/+30m/settle against that side, net of the half-spread and the 1.25% x p(1-p) rebate equivalent, is a direct empirical bound on the adverse selection the average resting order pays in these markets. It does not measure our queue position, but a negative average for incumbents is close to decisive for a new entrant with worse priority.
3. **Owner sets the hurdle H and the maximum capital now**, not at W7. With H and capital fixed, (1) and (2) become an arithmetic kill test.

One coupling worth knowing: the workstation's `data\` mirror is frozen at 2026-08-12 (`OPERATIONS_AGENT_ROLE.md:229-231`) and the execution tape started 2026-08-15, so the host that is allowed to do heavy analysis holds none of the tape. The tape is small; a targeted copy is cheap. (Inferred, not verified on the workstation.)

### Q4. Is "no new model-alpha work" coherent with "the central goal is a better forecast from our own information"?

As a decision, yes: given the evidence in Q2 (every lever closed, last own-information test null at power 0.06, replay untrustworthy, 3.2% MDE floor) pausing model work is defensible and arguably overdue.

As documentation, no. Canon carries four different goal statements at once:

- `AGENT_CONTEXT.md:5-9`: evaluate whether weather-only or market-aware estimates outperform market prices.
- `ESTABLISHED_FINDINGS.md:140-146`: "THE CENTRAL GOAL ... standing goal ... ordering rule for every future decision" is a better forecast.
- `ESTABLISHED_FINDINGS.md:22-39`: forecast is objective 3 of 3 after the 08-13 pivot; §0b-§0c "remain the canonical model-research standard" but are partly superseded.
- `STATE_OF_PLAY.md:9-12, 62`: forecast not among the objectives; "no ... new model-alpha work".

"Model-alpha" is also ambiguous in this project's vocabulary: alpha is the statistical error budget of `CAMPAIGN_LEDGER.md` (item 330:115-116 "No new statistical alpha allocation") as well as trading edge. An agent cannot tell from `STATE_OF_PLAY.md:62` whether exploratory, non-alpha-spending model work is permitted.

The deeper incoherence: if the forecast cannot beat the market and the maker "need not" use a model (`item-330:102-105`), then the model, calibration, promotion and most reporting machinery serve no live objective. Item 330 W8/W11 say so, but nothing has been retired.

### Q5. Infrastructure scale versus evidence of edge

- Scale (lead's figures, not re-measured): ~360k lines of Python, 413 test files, 73 ops scripts, 881 docs, 382 branches, 200 worktrees. 324 roadmap items, 289 complete (`active-backlog.md:12-22`).
- Output (project's own count to 2026-08-09): 617 commits, 130 missions, 31 retractions, 1 shipped improvement, 0 retrains, 0 trades (`HOW_WE_GET_THINGS_WRONG.md:15-24`).
- Since 2026-08-15 on master (my count from `git log`): 287 commits; 217 touch `src/weather/operations`, `scripts/ops` or `docs`; 26 touch `src/weather/market`; 1 touches `model`, `calibration` or `sources` (an archive-location change). By subject line, the dominant themes are cold archive/storage recovery, portable live host hardening, bootstrap/baseline reconciliation, and status documentation.
- Item 330 was meant to shrink the system: "A smaller active system should reach an honest economic decision sooner" (`:80-84`); "The plan must not become a six-week cleanup prerequisite for a one-day evidence question" (`:617-618`). Two weeks in, all 13 work-package boxes are unchecked (`:777-789`), against its own Batch A+B estimate of 5-9 focused days (`:607-608`); the simplification packages W8-W12 are unstarted; and new machinery was added instead (archive transfer/restore bridge, NTFS compression lane, night-recovery controller, reward simulator plus a third app page on the maker branch).
- Revenue ceiling at the authorised envelope is cents per day (rebate $0.06 per 20-share fill; gross paired spread $0.40; $1 minimum payout; `agent-report-2026-07-27...:337-350`). The infrastructure cannot be justified by the pilot; it can only be justified by a scale-up whose key parameter (`f`) nobody is measuring.

Sunk-cost risk is high and is visible in the pattern of decisions: each negative result (model edge 08-09, MM viability 07-27) was followed by a pivot to the adjacent track rather than by a stop/continue review, and each pivot inherited the full process overhead.

### Q6. Are there explicit kill criteria or a budget?

- Mission level: yes, and they work. Handoffs carry stop rules; the alpha ledger stops at 20 decisions (`CAMPAIGN_LEDGER.md:17-23`).
- Maker experiment level: partially. Item 330 defines G4 outcomes (continue / redesign / stop / inconclusive, `:245, 463-471`), a calibration budget (five attended sessions, two payout cycles, fourteen days after G2, `:425-429`) and a thirty-day exposure budget (`:481-485`). But the hurdle H is undefined (`:631`), the budgets only start after G2, and G2 requires live authority that is withheld (`:694`). The clocks therefore never start.
- Project level: none found. A search of `docs/` for kill/stop criteria, sunset, project/time/effort budget returned only mission-level stop rules and item 330's own clauses. There is no date, spend, or evidence threshold at which the project as a whole is paused, reduced to capture-only, or ended. There is also no recorded trigger for "reward programme withdrawn" or "venue access lost".

### Q7. Strategy-level single points of failure

- One production host, one disk, one operator. Off-host mirror paused since 2026-08-12 by owner decision, and the frozen copy was "already not proven restorable (exit 11; 8 restore problems of 19 checked)" (`OPERATIONS_AGENT_ROLE.md:229-234`). Closed owner decision; reported once, as accepted.
- Partial mitigation exists: ~79 GB of older source files are archived to private cloud storage with restore proofs (`STATE_OF_PLAY.md:31-33`); "earlier encrypted archives still require their preserved recovery keys", so key custody is itself a single point of failure.
- Disk: live state via lead is ~4 days of headroom. When the disk fills, objective 1 (capture) fails, and canon's ordered path has no storage step.
- Agents: coding agents' diagnostics have taken production down at least three times (2026-08-09 log rotation, 2026-08-23 host reset, plus the memory incidents). The same host is both the only production system and the place agents work.
- Venue: a single venue by standing decision; reward and rebate programmes are "non-contractual and can change or vanish daily" (`MARKET_MAKING_PLAN.md:57-58, 434-439`); geographic eligibility is "a hard gate for live trading" flagged since 2026-06-12 (`:460-461`). Git history shows canon briefly recorded the production host as venue-ineligible (`25054ae32`, 2026-08-23 16:39) and withdrew that 53 minutes later as an unsupported inference (`2d50bcb09`); the repository now deliberately asserts nothing about location (`INTERNATIONAL_MM_LIVE_PILOT.md:54-63`). I make no claim about the operator's location. The strategic question only the owner can answer, at zero cost: can the end state (a continuously running maker on the production capture host, profile `capture_colocated_v1`) ever satisfy the venue's eligibility and no-circumvention terms from where that host physically sits? If not, the end goal is reachable only through attended sessions on a relocated portable PC, which is not market making as the plan describes it.
- Knowledge: the authoritative record of the last two weeks (first live orders, the own-information challenger result, the 48-hour opportunity report) lives on unmerged branches and in ignored `scratch/handoffs/` paths on specific machines.

---

## 3. Findings

Severity scale per the audit brief. IDs are stable.

### strategy-1 (critical) - The ordered critical path is not executable in the current live state and omits the one thing about to fail

Claim: `STATE_OF_PLAY.md:42-58` step 1 (complete Windows host-suite qualification) and step 4 ("after reliability acceptance") cannot be admitted: the guarded suite refuses below 50 GiB free, the host has ~21 GB free and is filling ~5.9 GB/day, archive uploads are owner-paused, and the path lists no storage step. `STATE_OF_PLAY.md` was last rewritten 2026-09-13.

Evidence:
- `docs/operations/STATE_OF_PLAY.md:24` - "Ordinary qualification retains its 50 GiB disk floor."
- `docs/operations/STATE_OF_PLAY.md:44-46, 52-54` - step 1 requires the complete host suite; step 4 waits on reliability acceptance.
- `scripts/ops/bounded_worktree_test_suite.ps1:288-311` - `Assert-SuiteDiskHeadroom` throws below 53,687,091,200 bytes on the repo, worktree, log and temp volumes; invoked at `:365` and `:608`.
- `scripts/ops/integration_attempt_suite.ps1:168` - the guarded integration suite runs that script.
- `docs/operations/STATE_OF_PLAY.md:21` - uploads paused by owner. Live state via lead: 21 GB free, ~4 days headroom, storage-recovery one-shots failed 09-14..09-17, qualification a1..a11 failed.

Basis: verified_in_code for the floor and the path; live_state (via lead auditor) for the disk number. Known status: new as a statement about the path; the disk pressure itself is known_open.

Impact: the project's current plan of record is deadlocked at step 1 while the disk trajectory threatens objective 1 (irreplaceable capture) within days.

Recommendation: owner decision today on disk headroom (resume archive reclaim, or stop a named producer, or lower a named floor knowingly). Rewrite the ordered path with storage first and settlement repair second.

### strategy-2 (high) - No executable route to a viability decision, and no kill criteria

Claim: every decision gate in item 330 that measures economics (G2 lifecycle-for-economics, G3 calibration cohort, G4 frozen decision) requires live sessions; W5-W7 are "BLOCKED for real sessions by the owner's no-live instruction". The calibration and exposure budgets only start after G2. The hurdle H is undefined until W7. No project-level stop date, spend cap or evidence threshold exists.

Evidence:
- `docs/roadmap/items/item-330-...md:694` - W5-W7 blocked. `:241-245` - gates. `:425-429`, `:481-485` - budgets keyed to G2/freeze. `:631` - hurdle deferred to W7.
- `docs/operations/STATE_OF_PLAY.md:18-19, 42-58` - no live trading; no step in the path produces outcome evidence.
- Search of `docs/` for kill/stop criteria, sunset, project/time/effort budget: only mission-level stop rules and item 330's clauses.

Basis: verified in docs. Known status: the no-live instruction is known_accepted; the absence of H, of a project-level stop, and of any decision-producing step is new.

Impact: the project can run indefinitely at full process cost without ever reaching continue/stop. This is the sunk-cost mechanism.

Recommendation: owner writes one page now: hurdle H (dollars per month and maximum capital), a calendar date for the G1 desk verdict, the condition under which attended live sessions resume, and a capture-only fallback if G1 is negative.

### strategy-3 (high) - The refocus re-walks a track the project already closed with a decision-grade negative, under an unchanged risk envelope

Claim: the 2026-07-27 report concluded `NOT_VIABLE_CURRENT_TRACK` with a stated reopening condition (new risk envelope plus a predeclared reason to believe reward dollars cover toxicity). The envelope is unchanged; the 2026-09-11 opportunity work re-derived the same infeasibility (two-sided 20-share pair breaches the 10 pUSD ceiling); the founding plan measured rewards at ~$16/day fleet-wide. Neither the verdict nor the reopening condition appears in any canonical operations doc or in item 330.

Evidence:
- `docs/roadmap/agent-report-2026-07-27-workstation-mm-viability.md:5, 11-25, 249-255, 365-374, 513-519`.
- `docs/research/MARKET_MAKING_PLAN.md:100-108, 415-419`.
- `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md:76-83` - unchanged caps.
- Item 330 on `origin/codex/48h-maker-integration-20260912` (September 11 section): each simultaneous pair breaches the 10 pUSD per-order ceiling; `EVIDENCE_BLOCKED`.
- `docs/operations/ESTABLISHED_FINDINGS.md:441-450` records the arithmetic via commit `8e7b5732` and the 45.94% sensitivity result that re-opened spread capture; grep for `NOT_VIABLE` finds the verdict only in dated July reports.

Basis: verified in docs and git. Known status: new (the grounds are partly in canon; the verdict, its reopening condition, and the fact that item 330's "rewards" half contradicts both are not).

Impact: two weeks of W3/W4 engineering aimed at a revenue component the project had already measured as a rounding error and structurally unreachable at its own caps.

Recommendation: record the July verdict in canon; state in item 330 which of its grounds has changed; publish the reward-dollar ceiling (Q3 experiment 1) before any further W3/W4 provenance work.

### strategy-4 (high) - Canon is forked: master's read-first documents omit the two most decision-relevant events of September

Claim: (a) an attended Stage 0/1 live lifecycle with two real exchange orders passed on 2026-09-06/07 (commit `8739902fe`), and (b) the 12-field own-information challenger ran on 2026-09-02 with verdict `INCONCLUSIVE_UNDERPOWERED` (commit `f2722a4ed`). Neither commit is an ancestor of master. Master still says Stage 0 "FAILED CLOSED ... NEW ATTEMPT AND LIVE EVIDENCE OPEN" and that the surface-heating mechanism "was not tested in either direction".

Evidence:
- `git branch -a --contains ca64296fb` lists only `codex/*` topic branches, not master.
- `docs/roadmap/items/item-67-...md:1` (master heading); `docs/roadmap/active-backlog.md:30`.
- `docs/operations/ESTABLISHED_FINDINGS.md:1047-1049`.
- grep of master `docs/` for `pilot-20260907`, "Stage 0/1 passed/proved", "seasonal challenger", `INCONCLUSIVE_UNDERPOWERED`: no matches.
- `docs/operations/STATE_OF_PLAY.md:38-40` - the maker candidate and the documentation transaction sit behind reliability acceptance, which sits behind the host suite (strategy-1).

Basis: verified in git and docs. Known status: new.

Impact: agents do most of the work and start from canon. Canon currently misstates whether the project has ever touched the exchange and whether its flagship forecast test was run. Expect re-derivation and contradictory handoffs. The "documentation transaction" gate is now itself the reason documentation is wrong.

Recommendation: a roll-free, docs-only status correction to master recording both events and their branch locations; do not wait for PR 61/55 qualification.

### strategy-5 (high) - The cheapest decisive maker experiment is not being run: the public execution tape has no analytical consumer

Claim: the tape built specifically to supply "counterfactual markouts" has been collected since 2026-08-15 and is read by nothing except its health monitor. The paper fill simulator's trade inputs are four legacy files, two of which nothing in `src/weather` writes and two of which come from the enrichment loop disarmed on 2026-07-27.

Evidence:
- `src/weather/market/execution_tape_store.py:564` - writes `data/snapshots/<event>/execution_tape/`.
- `src/weather/market/mm_paper_scoring.py:1486-1505` - `load_trade_rows` reads `trades_long.csv`, `market_trades.csv`, `market_ws.jsonl`, `market_ws_events.csv` only.
- grep `execution_tape_store` across `src/weather`: importers are `execution_tape_capture.py:23`, `operations/execution_tape_supervisor.py:41`, `schema_registry_recent_data.py`. `operator_control_room.py:212-216` reads health only. grep for writers of `market_trades.csv|trades_long.csv`: none.
- Same reader list on `origin/codex/48h-maker-integration-20260912` (`mm_paper_scoring.py:1467-1468`); no markout/adverse-selection module in its `src/weather/market` or `reporting/market` trees.
- `docs/operations/ESTABLISHED_FINDINGS.md:398` - "`f` is now the single most decisive unmeasured number"; `:1964` - public tape supports counterfactual markouts; `:416` - newest `market_ws_events.csv` is 2026-07-27.

Basis: verified_in_code (importer trace plus reader list). Known status: new.

Impact: five weeks of the only new evidence stream sit unread while engineering goes to reward-provenance plumbing. A maker-side markout table could close or re-open the track without a cent at risk.

Recommendation: one bounded workstation mission: copy the execution-tape folders only, compute signed maker-side markouts by market/hour/price bucket with crossed clustering, compare with half-spread plus rebate equivalent. Pre-register the kill threshold.

### strategy-6 (medium) - Goal hierarchy is incoherent across canonical documents; "model-alpha" is ambiguous

Evidence: `AGENT_CONTEXT.md:5-9`; `ESTABLISHED_FINDINGS.md:22-39` versus `:140-146`; `STATE_OF_PLAY.md:9-12, 62`; `item-330:102-105, 115-116`. Basis: verified in docs. Known status: decision known_accepted; incoherence new.

Impact: agents read "THE CENTRAL GOAL ... ordering rule for every future decision" and a standing ban on the work that goal implies.

Recommendation: one goal statement, one place; mark §0b-§0c as historical; define "model-alpha" in one sentence.

### strategy-7 (medium) - The headline meter is still the streak; the clock that matters has no counter and is being starved

Evidence: `ESTABLISHED_FINDINGS.md:194-254` (streak gates nothing; "no counter at all"); `scripts/ops/streak_status.py:94-114`; 25 `streak` references in `scripts/ops/status.ps1`; no `promotion_countable`/date-cluster counter found under `scripts/ops` or `src/weather`; `ESTABLISHED_FINDINGS.md:622-624` (D=73 by 2026-10-16 for a 5% step); settlement repair is step 5 of 6 (`STATE_OF_PLAY.md:55-56`); live state via lead: 10 of 14 recent dates unsettled. Basis: verified_in_code for the meter, grep-level for the absence, live_state via lead. Known status: known_open.

Impact: every unsettled date that is not backfilled is a lost date cluster; the 10-16 confirmability date slips silently.

Recommendation: add a counter of post-boundary promotion-countable date clusters to the morning briefing; move settlement repair ahead of qualification work.

### strategy-8 (medium) - Effort allocation contradicts the refocus: process and storage work dominates, simplification has not started

Evidence: `git log --since=2026-08-15` on master: 287 commits; 217 touching operations/ops scripts/docs; 26 touching market; 1 touching model/calibration/sources. `item-330:607-618` (estimates and the "six-week cleanup" guard); `:777-789` (all boxes open); `HOW_WE_GET_THINGS_WRONG.md:15-34`. Basis: verified in git and docs. Known status: known_open in shape (Pattern 2/3), new as a measurement of the last five weeks.

Recommendation: a standing rule that each week must contain at least one task whose output is an outcome number (a Brier ratio, a markout, a dollar ceiling), and a freeze on new ops machinery until W9 deletions land.

### strategy-9 (medium, known_accepted) - Strategy-level single points of failure

One host, one disk, one operator, mirror paused since 2026-08-12 and never proven restorable (`OPERATIONS_AGENT_ROLE.md:229-234`); encrypted-archive key custody (`STATE_OF_PLAY.md:33`); single venue with non-contractual programmes and an eligibility gate that is resolved only at action time (`MARKET_MAKING_PLAN.md:434-439, 460-461`; `INTERNATIONAL_MM_LIVE_PILOT.md:54-63`; commits `25054ae32`, `2d50bcb09`). Reported once per the brief; the backup decision is the owner's and is closed. The eligibility question for the production-host live profile is the part worth the owner's private attention.

### strategy-10 (low) - Staged research inputs live in an unmanaged temp directory on the production host

`C:/tmp/pit-refetch-2026-08-10` and `-front` (1,645,056 rows, `ESTABLISHED_FINDINGS.md:716-732`) still exist alongside ~80 loose scripts and worktrees. They are re-fetchable ("no retention cliff", `:704-706`), so the risk is hygiene and disk, not loss.

---

## 4. Strengths

1. Candid, quantified self-audit. `docs/operations/HOW_WE_GET_THINGS_WRONG.md` and `RETRACTED_AND_FALSE_LEADS.md` are better than most organisations manage; the patterns they name are exactly the ones this audit found recurring.
2. Statistical discipline: crossed date x market clustering, power and MDE reported, a binding alpha ledger that has actually refused spends (`docs/operations/CAMPAIGN_LEDGER.md`), outcome-blind design freezes.
3. Live-money safety design: non-raisable caps, post-only, attended first sessions, credentials outside the repo, explicit no-circumvention eligibility gate (`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md:74-99`), a preregistered economics claim boundary (`docs/research/INTERNATIONAL_MM_PILOT_PREREGISTRATION.md`).
4. Item 330 is a good plan on paper: a correct accounting identity, separate revenue components, "profit is not required to close this item honestly", explicit refusal alternatives (`docs/roadmap/items/item-330-...md:86-91, 182-216`).
5. The negative results are trustworthy and permanent (`ESTABLISHED_FINDINGS.md:343-366`): nobody needs to search for a quotable model edge again.

---

## 5. What I could not cover

- `data/` entirely, including `MORNING_BRIEFING.md`; live numbers are the lead auditor's.
- GitHub PR state (no network). PR 55/61 status is as canon describes it.
- The workstation and its branches beyond two sampled tips; the 210 unmerged branches were not surveyed.
- `ESTABLISHED_FINDINGS.md` lines 1151-1749 and 2100-2383, 2530-2700; `HOST_LOAD_POLICY.md`, `DELEGATION_CONTRACT.md`, `architecture.md`, items 309, 325, 328, 66.
- Operator time and money spent; no record found.
- The venue's current geographic policy and reward rates (no network; doc_claimed only).
- Whether `hourly_model_performance` currently produces a usable served-vs-market number; it exists (`src/weather/reporting/hourly/hourly_model_performance.py`) but depends on settlements that are mostly missing.

## 6. Open questions for the owner

1. What monthly dollar figure, at what maximum capital, would make this worth continuing? (H)
2. Under what condition do attended live sessions resume, given Stage 0/1 already passed on 2026-09-06?
3. Can the production capture host ever be a lawful live execution host where it physically sits? If not, is attended-only portable execution an acceptable end state?
4. If the reward-dollar ceiling and the public-tape markout both come back negative, is capture-only (or stop) acceptable, and on what date is that reviewed?
5. Is the forecast still a goal, or now only a risk input? Canon should say one thing.
