# Operations agent role — handover snapshot of 2026-08-13 09:40

> **HISTORICAL — not current authority.** This was §7 of
> [`../OPERATIONS_AGENT_ROLE.md`](../OPERATIONS_AGENT_ROLE.md) until 2026-09-19. It records what the
> outgoing session believed at 2026-08-13 09:40 and was never maintained after that. Every number,
> branch tip, task name and "in flight" row below is stale.
> [`../STATE_OF_PLAY.md`](../STATE_OF_PLAY.md), code, task actions and generated receipts win
> wherever they differ.

**Read when:** you are tracing why a mid-August decision was made. **Do not read** for current
state, current priorities, or to decide what to merge.

**Where the still-live conclusions belong** (do not cite them from this page):

| Conclusion in this snapshot | Owner |
| --- | --- |
| Research threads closed (instrument audit, replay reproduction, observation recovery, reshaping, inputs, no quotable edge) | [`../ESTABLISHED_FINDINGS.md`](../ESTABLISHED_FINDINGS.md) and [`../RETRACTED_AND_FALSE_LEADS.md`](../RETRACTED_AND_FALSE_LEADS.md); the replay trace is [`../REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md`](../REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md) |
| The mirror is paused and the workstation copy is frozen | [`../mirror-paused-2026-08-12.md`](../mirror-paused-2026-08-12.md) |
| Never retire a date from a failure count; `status.ps1` GB/day caveat; the two fleet-generated config files | kept in the live role file, §5 and §8 |
| α accounting | [`../CAMPAIGN_LEDGER.md`](../CAMPAIGN_LEDGER.md) |

---

## The snapshot, verbatim

This section records what the outgoing session believed at 2026-08-13 09:40. It is intentionally
not maintained. [`STATE_OF_PLAY.md`](../STATE_OF_PLAY.md), code, task actions, and generated receipts
win whenever they differ. The snapshot remains only so old decisions can be traced.

**Capture.** Healthy today: `ON_TRACK`, 75 captures, 0.0 min max gap, all three loops `AboveNormal`.

**Streak: 0/14, broken at 3.** `08-12` carries `coverage_reason: "2 gap(s), max 40 min"` — see the
warning in §5, that was self-inflicted. `08-09`→`08-11` all graded `complete`. Lock projects
**~2026-08-25** if every day from `08-13` is clean.

**Settlement: every hole through `08-11` is CLOSED.** `08-08` recovered **12/12 with real
`daily_summary` sources** on the *fourth* attempt, after this file's predecessor had written it off
as "likely unrecoverable". **Never declare a date unrecoverable from a failure count alone** — a
count measures how often you retried, not whether the source has the data, and retirement stops the
retries that would have fixed it. Only a *reason* retires a date.
**`08-12` was still settling when this was written (09:30 run in flight) — verify it.**

**Disk is NO LONGER the lock's binding constraint.** 181.6 GB free, the most since 08-09.
Midnight-to-midnight burn is decelerating: −10.5, −5.3, −0.7 GB/day across 08-10/11/12, then +44 GB
on 08-13. `clob_order_book_tiering` now runs and passes every chain. **The −12.6 GB/day and the
~2026-08-23 exhaustion date are retired.** **Do not quote `status.ps1`'s headline GB/day** — it
references a sample up to 24 h back, so one discrete reclaim flips the sign (it read `+21.1 GB/day`
today; the disk is not gaining).

**The off-host mirror is PAUSED** (operator, 2026-08-12 — focus this host on stability first). Three
tasks Disabled, nothing deleted, restart is two `Enable-ScheduledTask` calls. The workstation's
`data\` is **FROZEN at 2026-08-12 05:03, not lagging** — a date after that does not exist there. The
frozen copy was **already not proven restorable** (exit 11; 8 restore problems of 19 checked).
`status.ps1` suppresses off the **task state**, so re-enabling restores alerting by itself.
Canon: `mirror-paused-2026-08-12.md`.

**Chain:** `deferred / terminal`, **9 steps BLOCK**, `live_variant_settlement_scorecard` FAILING →
`promotion_lane_blocked`. Expected pre-release, but the scorecard has been failing long enough to
deserve a trace rather than another shrug.

### Research state — nearly every lever is closed

**This matters more than any single finding: 31 retractions against ONE shipped win.** The dominant
failure is **measuring eligibility and calling it outcome**. Assume your exciting result is one of
the 31 until you have traced a single instance end to end.

- **Instrument audit CLOSED** (five missions, zero defects). The gap is **real**. Labels are FLAT;
  cite the **~13% ceiling**, never the 1.5069% point.
- **Replay thread CLOSED — never dispatch another historical-reproduction mission.** We serve bytes
  that were never committed: 324 of 413 fingerprints match no blob in 178 refs. It is a
  **commit-discipline defect, not a replay defect.**
- **Observation-recovery thread CLOSED, unpowered, α unspent** (`-09-78a`). The limit was the
  stratum's **11 date clusters**, not the 12-market floor; ~22 would flip it.
- **Distribution reshaping is closed** (`-09-60a`), **inputs were not the gap** (`-09-44a`, a precise
  null), **no quotable edge anywhere** (`-09-46a`, 114 cells, zero positive).
- **The remaining lever is knowing MORE**, not reshaping what we know.

### In flight / pending

| Item | State |
| --- | --- |
| `WeatherSuite0969a` | Fires **2026-08-13 20:30**. The operator approved continuous execution capture on 2026-08-13; merge `-09-69a` **only** on `VERDICT: ALL CHUNKS PASSED (22/22)`. **ROLL-SENSITIVE** — `schema_registry_recent_data.py`, so merge in the quiet window. Branch `origin/codex/workstation-execution-tape-capture-2026-09-69a` @ `98edaaa2`, worktree `C:/tmp/wt-09-69a`. Its `0x1` is historical until the armed suite runs |
| Execution-tape continuous capture | **APPROVED, NOT YET RUNNING.** Pilot proved the tape exists. The suite, quiet-window merge, runtime start, and proof of real rows are still required. Do not start harvest-lane code before those rows exist |
| International rebate economics | **BUILT, NOT MERGED** on local branch `codex/international-rebate-pivot` @ `c4dd0390`. It binds paper economics to current International condition/token evidence, forces primary liquidity rewards to zero without paid evidence, and leaves live-trade permission false. Run the latest focused tests after 18:00, merge in the quiet window, collect a fresh snapshot, then explicitly accept the baseline |
| Season-window re-fetch | Archive covers **05-10→06-30, ZERO Jul/Aug**. Permitted and **still un-run**. Flagged CRITICAL by the staleness sweep |
| Forward capture fix | Hash `sys.modules` after import; immutable content-addressed bundle. Written into canon, **not dispatched** — rolls the fleet, needs the operator's call |
| Identity v0.2 fix | BUILT, **not merged** (`4050f1ee`). ROLL-SENSITIVE |
| MM track | **Execution capture first, paper harvest lane afterwards.** The order is load-bearing. The blocker is absent execution evidence, not the gates — the continuity gate is CORRECT |
| Heavy-step defer | Defers on `live_capture_loop_active` with `active_window_source: fail_closed_live_default` and both window hours `null`. **Worth a trace** — capture is always "healthy" by design here |
| Known-failing tests | `test_source_tree_strict_audit`, `test_tracked_artifact_manifests`, `test_afternoon_residual_centering`. Pre-existing, out of scope |

The working tree normally carries two fleet-generated modified files
(`config/location_market_events.json` and `config/locations.json`). Routine churn — leave them
uncommitted. The guarded quiet-window merge is the sole cleanup exception: after its immutable-tip
guard passes, it commits exactly those two paths so its rollback point cannot discard generated
state. The live scheduler inventory belongs under ignored `data/alerts/OPERATING_SCHEDULE.md`.

## Update this file when

Never, except to correct a broken link. It is a frozen record.
