# State of play

**Last rewritten: 2026-08-13 22:45 (scheduler collisions removed, host work serialized,
and the Stage-2 evidence path corrected).** Read this first, then
`ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` for evidence.

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
| Capture streak | Reset. `08-13` is partial after the evidence-refresh incident (§8d); earliest new full day is `08-14`. |
| MM countable days | Stopped. A countable day never required a `QUOTE` (§8b). |
| Archive coverage | Does not include the current target period; the permitted re-fetch remains un-run. |
| Execution evidence | No economic counter exists. Public-tape merge/proof are armed, but public trades cannot prove our fills or P&L (§8c). |

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
- A live test is authorized only from a genuinely eligible **International** host: exactly one
  market, finite non-raisable 100 USDC-equivalent cap, post-only, no naked sells, and all existing
  risk/readiness gates. Ontario production never receives credentials or places/cancels orders.

## In flight

| Work | State / next action |
| --- | --- |
| Public execution tape (`-09-69a`) | Corrected exact tip passed its bounded suite. Guarded merge is armed for 01:30 and bounded proof for 02:15. The original identity/counting claims remain rejected. |
| International rebate economics | Tested, not merged. Content-bound official terms and realized payout evidence exclude unpaid incentives from acceptance P&L. Rebase/review before quiet-window integration. |
| International live probe | Stage 0/1 tested at exact tip `904ce2d8`; exact full suite is armed for 04:30 and source bundle for 08:40. Stage 2 bounded maker-session code is the missing implementation. Build it library-only on the separate stage2 branch; run it only on the eligible host after readiness passes. |
| Observation recovery (`-09-73a`…`-09-78a`) | Thread closed unpowered; alpha unspent. Leave the draft unfrozen (§5e). |
| B-only screen (`-09-63a`) | Stopped at Gate 3. The report remains branch-only; do not re-register the panel-size gate unchanged (§1j). |
| PIT extract / fields | Extract is shipped; staged fields are not adopted because adoption changes serving. Replay first (§1e). |

Legacy `WeatherMergeQueueDriver` and `WeatherMergeSensitiveDriver` are **Disabled**. Their old
branch-only queues lacked immutable expected-tip binding and could collide with guarded work.
The repository-owned v1 driver requires reviewed full SHAs; do not re-enable either recurring
driver until valid queues exist. Never delete held branches.

## Operations — what is actually wrong today

- **Capture recovered; `08-13` did not.** A terminated evidence wrapper left its child alive and
  starved capture. Job ownership now proves child-tree teardown, but the workload remains unsafe
  beside capture. `WeatherEveningEvidenceRefresh` stays **Disabled** (§8d).
- Heavy wrappers now share one OS-held workload lease. Tonight's training is deliberately skipped
  and automatically re-enabled at 03:30 so it cannot overlap the 01:30/02:15 proof sequence.
  Task Scheduler Operational history is enabled. `status.ps1` now performs bounded EOF-seeking
  settlement checks instead of repeatedly rescanning large ledgers.
- The Stage-A daily wrapper owns its child tree and stops it at 11:55. Agent/ad-hoc heavy work is
  limited to 00:30–09:00; the scheduled Stage-A chain is the only 09:30–11:55 exception. Nothing
  heavy runs during 12:00–18:00 grading or 18:00–00:30 near-close capture.
- Settlement holes through `08-11` are closed. A failure count does not prove a date is
  unrecoverable; verify row content and source identity (§8d and settlement findings).
- The off-host mirror is operator-paused. Its frozen copy is neither current nor proven
  restorable; task state controls alert suppression. See `mirror-paused-2026-08-12.md`.
- Memory commit is no longer at its former ceiling. The remaining admission deferral cites
  always-live capture rather than memory pressure and deserves a separate trace; do not weaken it.
- Disk is not the current binding constraint because CLOB tiering is reclaiming space. Keep raw
  order books as canonical evidence; do not quote the lagging status headline as a burn rate.
- Log rotation remains a capture risk: reopening a large JSONL and breaker reads can stall loops.
  The regrowth mechanism is not yet prevented.

## Daily reads and update rule

Read `STALENESS_SWEEP.md`, `MORNING_BRIEFING.md`, `MM_COUNTABILITY.md`, and
`data/backtest/daily_refresh_report.md`. `OPERATING_REFERENCE.md` is generated. Merge timing comes
only from `roll_verdict.ps1`. Expected blocked task exits do not imply master is green.

Update this file only when a decision changes, the critical path moves, or a mission returns.
Replace stale text; if adding a fact, identify what became untrue.
