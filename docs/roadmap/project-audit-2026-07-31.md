# Project audit — 2026-07-31 (waiting on the streak: state, findings, and the path to the best model)

Read-only audit taken at 22:48–23:05 local, 2026-07-31. No fixes were applied. Every number below was
read tonight from a live artifact unless marked otherwise; artifact paths are cited inline.

## Verdict

The things that must be green are green: the streak is 10/14 with today clean, three independent code
paths agree on which days count, the capture fleet is healthy, and the serving-floor fix is live and
measured. Every blocked subsystem — nightly retrain, the vs-market scorecard, the replay-cache
reclaim, MM promotion — is blocked on the *same* missing object, release #1, which the lock (~08-03)
plus the consolidation branch (armed tonight) plus the synthetic rehearsal (in flight on the
workstation) are already converging on. The audit found no new lock blocker. It found one degradation
(the maker lost its second live-forward day), one controllable host risk (a pending OS reboot), and
two model-repair experiments that have been sitting ready-to-run since June.

## 1. Verified healthy tonight

- **Streak 10/14** (`scripts/ops/streak.ps1`): day 1 = 07-21, most recent complete = 07-30, last 8/8
  complete. Today: 180 captures, zero in-window gaps, 12:00–18:00 covered. Lock ~2026-08-03 if 07-31
  → 08-03 stay clean.
- **Three-way agreement on day classification**: `streak.ps1`, `release_admissibility_clock`, and
  production preselection classify 07-14 → 07-29 identically (07-17/19/20 partial, rest complete).
  High confidence the clock is honest.
- **Capture fleet**: all three loops (snapshot_tracker pid 8860, clob_books pid 18016,
  observation_triggers pid 19424) AboveNormal, heartbeats ≤ seconds old, zero consecutive errors,
  zero stale-code markets (read from tonight's MM liveness probe).
- **Serving-floor fix live** (master `42749c98`, merged 01:15 today): served/market 1.664x → 1.498x,
  Toronto 1.242x → 1.175x, impossible mass 1363.94 → 0, over-final floor audit 0/12,813.
- **Tonight armed**: 01:15 release consolidation (`-08-01b`), 01:50 floor monitor (`-31e`), 02:25
  frontier (`-31f`). The workstation has already pushed its pre-start branch for the synthetic
  rehearsal (`codex/workstation-synthetic-rehearsal-2026-08-01c` @ master tip — no handback yet).
- **Mirror**: ok, 17.6 h ago, restore-verified 16/17.

## 2. Findings

**F1 — The maker lost live-forward day 2 (medium; watch, don't fix tonight).**
`data/mm_runs/2026-07-31/20260731T170937790302Z/live_forward_gate.json`: status **BLOCK**,
`counts_toward_live_forward_gate: false`, `can_still_count_live_forward_day: false`. Root cause:
`stale_or_missing_clob_book_rows` for **los-angeles** (1 of 12 markets; the other 11 quoted fine).
Separately, the run started at **13:09**, not 07:05 — `WeatherMarketMakingDailyRoll` last ran 07-30
19:30 and next fires **08-01 07:05** (today's 07:05 never fired; the supervisor started the run late).
So after day 1 (07-30, 12/12 countable) the live-forward record is 1-for-2. Verify tomorrow: the
07:05 trigger fires, and whether LA books recover (`python -m weather.market.market_microstructure
ensure` is the gate's own suggested remedy if not).

**F2 — Pending OS reboot on the host (controllable lock risk).**
`status.ps1` reports `reboot pending: True`, uptime 251 h. An OS-forced restart picks its own time;
the fleet is S4U and self-recovers, but a forced restart inside 12:00–18:00 on any of the last three
streak days could cost the lock. A **controlled** reboot in a quiet window (after tonight's merges,
before 04:00, or tomorrow pre-noon) removes the risk. Operator's call — not done tonight.

**F3 — Disk slope now intersects the build window (parked, but quantified).**
112.3 GB free at −15.2 GB/day → exhaustion ~08-08; the 7-day build window runs to ~08-10 and the
build consumes disk. Unchanged decision: reclaim is parked, offsite move is the eventual answer, and
release #1 itself unlocks the 32.3 GB replay cache plus CLOB tiering (~15 GB/day). Flagged only
because the two dates now overlap; if the build starts on time the pointer arrives before the wall.

**F4 — Nightly retrain still parks in seconds (by design; release #1 restarts it).**
`data/backtest/nightly_retrain_status.json` (refreshed 01:00 today): `status: blocked`,
`candidate_release: BLOCK / captured_input_replay_parity_blocked`, activation NONE. No production
model update since **07-12**. This is the gate doing its job with no release identity to bind parity
against — but it means 19 days of captured data have taught the production model nothing yet.

**F5 — The lane we serve still has no vs-market scoreboard (unchanged; resolves with release binding).**
`data/backtest/live_variant_settlement_scorecard.md` (refreshed 12:10 today): **BLOCK**, 0 valid
prediction partitions of 41,264 eligible, runtime identity fragmented across `legacy-runtime:*`
pseudo-identities. The daily-progress claim ledger (`daily_progress_ledger_report.md`, 23 rows) gates
every market-beating claim BLOCK, first blocker `weather_only_model_proof_packet is missing`, rolling
daily-first skill −0.71, positive skill days 0. The claims discipline works; there is simply no bound
identity to score yet.

**F6 — Two model-repair experiments have been READY_FOR_OPERATOR_REVIEW since 06-23, never run.**
`data/backtest/model_market_disagreement_analysis.md`: seattle 64–65 F exact-band/winner-centering
replay and seattle 66–67 F warm-tail dampening replay — both marked countable as evidence,
auto-change disallowed, next experiment named. These are replay-only (zero streak risk) and are
exactly the kind of work the wait is for.

> **CORRECTION, same night.** F7 below files the repo-root `logs/` residue as low-priority
> housekeeping. That was wrong: it sat directly on the release #1 critical path. The build's
> clean-source-tree gate excludes only `artifacts/releases`, `artifacts/candidates` and `data`, so
> those two untracked files made `git_dirty` true and would have failed the build's first command.
> Fixed at `aaf8252b`; full analysis in `docs/operations/RELEASE_ONE_BUILD_RUNBOOK.md` §1. The
> recurring `config/` half of the same gate is unfixable by ignoring and is now a build step.

**F7 — Housekeeping (low).** Five inert branches (`bootstrap-rehearsal-2026-07-23`,
`pit-simplex-2026-07-24`, `lock-blocker-fixes-2026-07-24`, `release-one-rehearsal-2026-07-29`,
`mm-gate-2026-07-28b`) are retirable — their code already landed; only their handback reports differ.
Repo-root `logs/` is untracked residue from the 07-21 backfill (two files). The dirty
`config/location_market_events.json` + `locations.json` are the automated 6-hourly refresh — normal.

## 3. Model quality snapshot (read tonight)

Price-free scorer (`data/backtest/price_free_model_learning_report.md`, refreshed 12:09 today —
diagnostic, not promotion evidence): 528 market-days, 05-28 → 07-30, 136,081 hourly checkpoints,
0 score errors. **Brier 0.0617, log loss 0.242, ECE 0.0195, top-band hit 44.8%.**

The hour-by-hour shape is the map of where skill is missing:

| Window | Brier | Reading |
| :--- | :--- | :--- |
| 03:00–06:00 | 0.077–0.079 | predawn — worst lane, most headroom |
| 09:00–14:00 | 0.068–0.076 | the primary-objective window |
| 15:00–16:00 | 0.056–0.059 | ramp resolves |
| 17:00 | 0.046 | best (and evening floor defect now fixed) |

Vs the market (replay, post-floor-fix): served lane 1.498x market Brier fleet-wide, Toronto 1.175x,
and Toronto at parity in the 09–14 window on ~9 effective days (underpowered, not a win). The gap is
**98.88% resolution / 1.12% reliability** — information, not calibration; ECE ~0.02 confirms
calibration is already near-solved. Worst market: dallas (0.0694); best: austin (0.0519); toronto
second-best (0.0546). The frontier decomposition (07-31f) attributes 87.97% of the combined
09:00–14:00 excess to resolution loss, with Dallas the largest F-market contributor.

## 4. The best path to the best model

**One answer: everything compounds through release #1, and nothing compounds without it.** The
retrain loop, the scorecard identity, MM promotion, and the replay-cache economics are all gated on
the same pointer. So the path, in order:

1. **Protect the lock (now → 08-03).** Four clean days. The streak is the only input that cannot be
   parallelized, rehearsed, or bought back.
2. **De-risk the build (now, in flight).** The synthetic post-preselection rehearsal is the
   highest-leverage work of the wait: no contiguous 14-day window has ever existed, so every
   downstream failure found now is free; found after 08-03 it is paid out of the 7-day window.
3. **Build release #1 and bind the served lane to an identity (08-03 → ~08-10).** This restarts
   nightly retrain (F4), gives the scorecard a scoreable identity (F5), unlocks 32 GB + tiering
   (F3), and opens the MM promotion gate.
4. **Stand up the live scoreboard on the served lane.** We have never scored what we actually serve
   against the market on live days. Toronto's 09–14 parity question (handoff `-08-01a`) is answered
   by accumulation, not more replay.
5. **Close the information gap, not the calibration gap.** Recalibration is provably near-exhausted.
   The candidates, in evidence order: forecast layer already proven +0.027 in ablation; 850 hPa
   temp / mixing height (item 32); soil moisture; forecast shortwave; smoke/AOD. Target the 09–14
   window and predawn — evening is solved.
6. **Attack Dallas with pooled training + city features.** Worst market on both independent
   measurements; the pooled-F harness already exists (item-224 artifacts). A fleet whose worst market
   improves lifts the F-served ratio fastest.
7. **Then MM converts parity into profit.** With maker rebates and rewards, a parity model is
   profitable; the $100 live test follows release #1 as already decided.

## 5. What to do during the wait

**Zero streak risk (start anytime):**
1. Synthetic rehearsal — in flight on the workstation; review the handback hard when it lands.
2. Run the two READY disagreement replays (F6) — replay-only, evidence-countable.
3. Write the release #1 build runbook: the ordered commands, gates, and expected artifacts for the
   7-day window, so the build is execution rather than discovery. Fold in the lock-day checklist
   (both clocks at 14 from the same start date; regenerate both sides of the 07-31 `rows[-1]`
   boundary; flip the floor monitor to fail-closed; no roll-sensitive merge armed lock night;
   snapshot `clock.json` + receipt hashes).
4. Chase the first claim-gate blocker: find what produces `weather_only_model_proof_packet` and what
   it needs — it is the named gate between us and ever making a defensible "beats market" claim.
5. Branch hygiene: retire the five inert branches; delete the stale repo-root `logs/` residue.
6. Wire `contiguous_pass_days` into `status.ps1` once tonight's consolidation lands (ps1-only,
   roll-free).

**Quiet-window only:**
7. Tonight's three armed merges — nothing else tonight; respect the 6-restarts/24 h budget.
8. Controlled reboot to clear the pending-reboot flag (F2) — operator decision.

**Watch, don't touch:** tomorrow's 07:05 maker fire and LA book freshness (F1); daily grades for
07-31 → 08-03; disk slope vs build start.

**Explicitly not now:** merging `workstation-research`, the hardening branch (needs B1/B3), or
`live-canary-bot`; disk reclaim (operator-parked); backups (deprioritized until profitable); paid
providers.

## 6. Ranked risks to the 08-03 lock

1. **Power loss** — 5 unexpected shutdowns/90 d, unaddressed; a UPS remains the single best purchase.
2. **Pending OS reboot** firing uncontrolled inside a capture window (F2 — controllable).
3. **Tonight's three fleet rolls** vs the restart budget (consolidation already cut this from three
   branches' worth of conflicts to one file).
4. **A Toronto capture wobble** of the kind LA showed today (F1 was on a non-streak market; the same
   staleness on Toronto costs a day).
5. **Post-preselection first-run failures** landing inside the build window (mitigation in flight).
6. **Disk** (F3) if the build slips past ~08-08.
