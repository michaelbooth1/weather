# State of play

**Last rewritten: 2026-08-14 19:20 (bounded Stage 2 is pre-stacked on the unified-client line;
the combined Stage 0/1 tip still awaits tonight's exact suite).** Read this first, then `ESTABLISHED_FINDINGS.md`
and `RETRACTED_AND_FALSE_LEADS.md` for evidence.

> **REWRITTEN, never appended. Capped at ~90 lines.** This page answers *what is happening now*.
> Findings and numbers belong in `ESTABLISHED_FINDINGS`; false claims in
> `RETRACTED_AND_FALSE_LEADS`; invariants in `AGENT_CONTEXT`; cross-host mechanics in
> `DELEGATION_CONTRACT`. Do not cite this page as quantitative evidence.

**Objectives:** protect capture continuity; make the **International Polymarket** market maker
profitable after costs from spread plus documented maker rebates; get the weather model close
enough to the market to control adverse selection and inventory. **We do not beat the market.**

## Current clocks

| Clock | Current state |
| --- | --- |
| Capture streak | Reset. `08-14` is currently `ON_TRACK`; it is the earliest possible new full day after the `08-13` incident. |
| MM countable days | Today's paper run is countable after the target-date validation producer was repaired. It has zero quote permissions; a countable day never required a `QUOTE` (§§8b, 8m). |
| Archive coverage | Does not include the current target period; the permitted re-fetch remains un-run. |
| Execution evidence | The bounded public-tape pilot passed. Continuous supervision is integrated, but the recurring producer is held Disabled pending the exact queued launcher repair; no own-account economic counter exists (§§8c, 8o). |

## Closed decisions — do not relitigate without new evidence

- **International-only maker-rebate pivot approved 2026-08-13. Never use Polymarket US.** The
  model is a quote-centre and risk-control input, not assumed alpha. Profit must survive spread,
  adverse selection, inventory, fees, and only rebates actually documented as paid.
- The instrument audit, observation-recovery candidate, reshaping, input, and old model-edge paths
  are closed or unpowered. The surviving shipped model change is the serving floor. See §§1, 1b,
  1i, 4, and 5e; do not resurrect retired headlines from roadmap correspondence.
- **No alpha is allocated.** Decision 10 remains closed unused and must never be reassigned.
- Release #1 remains deferred; release machinery is off the rebate-pilot critical path.
  Free-tier weather sources only; no paid provider.
- Public execution capture and own-account lifecycle evidence answer different questions.
  Public data supplies market paths/counterfactual markouts. Authoritative user events, open
  orders, positions, fees, and rebate receipts supply our realized lifecycle and economics (§8c).
- The operator designated this 16 GB production PC as the eventual **International** execution host
  after it is physically relocated. While its current official geoblock evidence is Ontario/blocked,
  it remains read-only and receives no credential import. Relocation removes the obsolete source-
  transfer step; it does not waive a fresh official unblocked response, exactly one market, the finite
  non-raisable 100 pUSD-equivalent cap, post-only/no-naked-sell rules, or any existing gate.

## In flight

| Work | State / next action |
| --- | --- |
| Public execution tape (`-09-69a`) | Continuous public-only supervision is integrated. The first real adoption refused a Windows venv launcher/worker PID mismatch and the task remains Disabled. The predecessor repair tip passed its pre-quiet immutable full suite; its branch is now refreshed onto the combined Stage 0/1 parent and focused-green, but must pass a new exact-tip suite, guarded merge, and fail-closed adoption tonight. This is public path evidence only, never fills, intensity, rebates, or P&L (§8o). |
| International rebate economics | Historical legs now bind only to atomically frozen per-run snapshots in a bounded stream. Its exact-green repair is included in the refreshed cumulative Stage 0/1 tip, which supersedes the standalone repair as the preferred integration target. |
| International live probe | The refreshed current-production + economics + Stage 0/1 successor is pushed and focused-green. Because merging current production created a new exact tip, its old suite proof does not qualify it; the 08-15 00:30 exact-tip suite and 01:00 suite-gated merge must refuse if identity, resource, receipt, or capture guards fail. The failed old tip remains ineligible; its immutable bundle task refused and produced no artifact. The cumulative successor migrates the official adapter to `polymarket-client==0.6.0` with a no-deploy wallet preflight, one-submit post-only path, and current heartbeat contract. After integration and physical relocation, a separately reviewed fixed-scope wrapper on this PC is still required before authenticated Stage 0 or either Stage 1 mutation (§8k). |
| Paper-only market harvest | The `market_harvest` permission lane is implemented on the combined Stage 0/1 parent and included in the cumulative client-upgrade successor. It can issue bounded paper quote permission from current International books and event state without claiming model edge or promotion, but cannot select `live-pilot`. After Stage 0/1 and the execution-tape repair land, refresh the cumulative successor onto production, run an exact-tip full suite, and merge it only through the guarded quiet-window path. A real active-market paper tick must emit permission before either Stage 1 mutation is eligible. |
| Bounded maker Stage 2 | The bounded Stage 2 delta is now pre-stacked on the cumulative unified-client/market-harvest line. Focused integration checks pass, including rejection of the retired v1.1 SDK/heartbeat contract, but the combined tip has no immutable full-suite proof and is not integration- or live-ready. Land Stage 0/1 first, refresh this stack onto that production plus the execution-tape repair, run a new exact-tip suite, merge only in a later quiet window, and review the relocated-host fixed-scope wrapper. Integration alone cannot authorize a submit (§§8m, 8n). |
| Snapshot fatal-gap bound | The prepared roll-sensitive branch passed its immutable full suite with every capture admission healthy. It predates the S4U registrar repair now on production, so it still needs current master merged into it, a fresh exact-tip suite, guarded quiet-window adoption, and live stop-to-recovery timing before the backlog item can close (§8l). |
| Observation recovery (`-09-73a`…`-09-78a`) | Thread closed unpowered; alpha unspent. Leave the draft unfrozen (§5e). |

Legacy `WeatherMergeQueueDriver` and `WeatherMergeSensitiveDriver` are **Disabled**. Their old
branch-only queues lacked immutable expected-tip binding and could collide with guarded work.
The repository-owned v1 driver requires reviewed full SHAs; do not re-enable either recurring driver
until valid queues exist. Never delete held branches.

## Operations — what is actually wrong today

- **Capture is healthy; `08-13` is not recoverable.** A terminated evidence wrapper left its child
  alive and starved capture. Job ownership now proves child-tree teardown, but the workload remains
  unsafe beside capture. `WeatherEveningEvidenceRefresh` stays **Disabled** (§8d).
- Built-in non-deleting log rotation is now live. Adoption preserved timestamped archives, opened
  small live sidecars, retained breaker history, and passed exact-source recovery for all capture
  workers. Log regrowth is no longer the open backlog item; archive retention remains deliberate.
- Snapshot, CLOB, and observation workers now use cadence-aware freshness and readoption proof.
  Guarded merges require every worker healthy and require heartbeat advance only from workers whose
  loaded source actually changed. Status treats an exact-tip merge failure as spent only when Git
  proves that full tip is already in production; unreadable or unintegrated tips still flag.
- Heavy wrappers share one OS-held workload lease. Ordinary heavy work is admitted only during the
  overnight window; the named Stage-A chain is the sole late-morning exception and owns a hard
  teardown. Nothing heavy runs during grading or near-close capture.
- The frozen International suite failed; its refreshed successor passed separately, then merged
  newer production and therefore requires a fresh exact-tip suite. The old tip's
  08:40 bundle ran, refused the failed receipt, and created no artifact. `WeatherTrainingWindow` is
  intentionally Disabled for one 08-15 integration night so it cannot stop capture during the
  01:00 guarded merge; the independent 04:15 restore stays armed and a 04:20 one-shot re-enables
  the daily window. Do not reinterpret bundle absence or a fail-closed merge as an incident.
- `WeatherExecutionTapeSupervisor` is intentionally Disabled after its first adoption exposed the
  Windows venv launcher as a parent of the true status/lock owner. The repair branch adopts only
  an exact verified direct child and adds a post-merge guard that tears back down on disagreement.
  Do not manually enable the task ahead of the queued exact-suite and guarded-merge chain.
- Windows Update installed current security updates after the temporary notify-only override was
  removed and now reports a pending reboot. Do not reboot in the graded window; coordinate a
  controlled off-window restart with session/push continuity and prove unattended S4U recovery.
- Settlement holes through `08-11` are closed. A failure count does not prove a date is
  unrecoverable; verify row content and source identity (§8d and settlement findings).
- The off-host mirror is operator-paused. Its frozen copy is neither current nor proven
  restorable; task state controls alert suppression. See `mirror-paused-2026-08-12.md`.
- Memory commit is no longer at its former ceiling. The remaining admission deferral cites
  always-live capture rather than memory pressure and deserves a separate trace; do not weaken it.
- Disk is not the current binding constraint. The recent alarm measures a one-day burst rather
  than an established steady burn, and the available evidence does not assign that burst to a
  single cause. Keep raw order books as canonical evidence and keep monitoring the longer windows.

## Daily reads and update rule

Read `STALENESS_SWEEP.md`, `MORNING_BRIEFING.md`, `MM_COUNTABILITY.md`, and
`data/backtest/daily_refresh_report.md`. `OPERATING_REFERENCE.md` is generated. Merge timing comes
only from `roll_verdict.ps1`. Expected blocked task exits do not imply master is green.

Update this file only when a decision changes, the critical path moves, or a mission returns.
Replace stale text; if adding a fact, identify what became untrue.
